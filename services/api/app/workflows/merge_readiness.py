import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter_ns

from app.connectors.errors import ConnectorUnavailableError, FixtureNotFoundError
from app.connectors.models import (
    ConnectorRequest,
    ConnectorSource,
    GitHubPullRequest,
    JiraIssue,
)
from app.connectors.protocols import GitHubConnector, JiraConnector
from app.policy import evaluate_merge_readiness
from app.policy.models import MergeReadinessResult
from app.observability import (
    FailureCategory,
    NoOpRuntimeTelemetry,
    PersistenceCheckpoint,
    RuntimeTelemetry,
    StepOutcome,
)
from app.observability.runtime_telemetry import SpanObservation
from app.runtime import (
    MergeReadinessRun,
    ExplanationSource,
    RunRepository,
    RunSources,
    RunStatus,
    RuntimeErrorCode,
    RuntimeErrorInfo,
    RuntimeStep,
    StepStatus,
    WorkflowStepName,
    create_pending_run,
    create_pending_step,
    transition_run,
    transition_step,
)
from app.runtime.errors import (
    RunPersistenceError,
    RunRecordInvalidError,
    RunStateConflictError,
)


PolicyEvaluator = Callable[
    [GitHubPullRequest | None, JiraIssue | None],
    MergeReadinessResult,
]
TimestampClock = Callable[[], datetime]
DurationClock = Callable[[], int]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _replace_run(run: MergeReadinessRun, **updates) -> MergeReadinessRun:
    values = run.model_dump()
    values.update(updates)
    return MergeReadinessRun.model_validate(values)


class MergeReadinessWorkflowService:
    def __init__(
        self,
        github_connector: GitHubConnector,
        jira_connector: JiraConnector,
        run_repository: RunRepository,
        policy_evaluator: PolicyEvaluator = evaluate_merge_readiness,
        timestamp_clock: TimestampClock = _utc_now,
        duration_clock: DurationClock = perf_counter_ns,
        telemetry: RuntimeTelemetry | None = None,
        explanation_provider: ExplanationSource = ExplanationSource.FAKE,
    ) -> None:
        self._github_connector = github_connector
        self._jira_connector = jira_connector
        self._run_repository = run_repository
        self._policy_evaluator = policy_evaluator
        self._timestamp_clock = timestamp_clock
        self._duration_clock = duration_clock
        self._telemetry = telemetry or NoOpRuntimeTelemetry()
        self._sources = RunSources(
            github=github_connector.source,
            jira=jira_connector.source,
            explanation=explanation_provider,
        )


    def _save_synchronously(
        self,
        run: MergeReadinessRun,
        checkpoint: PersistenceCheckpoint,
    ) -> None:
        with self._telemetry.checkpoint(checkpoint):
            self._run_repository.save(run)


    async def _save(
        self,
        run: MergeReadinessRun,
        checkpoint: PersistenceCheckpoint,
    ) -> MergeReadinessRun:
        await asyncio.to_thread(self._save_synchronously, run, checkpoint)
        return run


    async def _start_step(
        self,
        run: MergeReadinessRun,
        name: WorkflowStepName,
    ) -> tuple[MergeReadinessRun, RuntimeStep, int]:
        pending_step = create_pending_step(name)
        run = await self._save(
            _replace_run(run, steps=(*run.steps, pending_step)),
            PersistenceCheckpoint.STEP_STARTED,
        )

        running_step = transition_step(
            pending_step,
            StepStatus.RUNNING,
            self._timestamp_clock(),
        )
        run = await self._save(
            _replace_run(run, steps=(*run.steps[:-1], running_step)),
            PersistenceCheckpoint.STEP_STARTED,
        )
        return run, running_step, self._duration_clock()


    def _duration_ms(self, started_at_ns: int) -> int:
        elapsed_ns = max(0, self._duration_clock() - started_at_ns)
        return elapsed_ns // 1_000_000


    async def _complete_step(
        self,
        run: MergeReadinessRun,
        step: RuntimeStep,
        started_at_ns: int,
        **run_updates,
    ) -> MergeReadinessRun:
        completed_step = self._build_completed_step(step, started_at_ns)
        return await self._save(
            _replace_run(
                run,
                steps=(*run.steps[:-1], completed_step),
                **run_updates,
            ),
            PersistenceCheckpoint.STEP_COMPLETED,
        )


    def _build_completed_step(
        self,
        step: RuntimeStep,
        started_at_ns: int,
    ) -> RuntimeStep:
        return transition_step(
            step,
            StepStatus.COMPLETED,
            self._timestamp_clock(),
            duration_ms=self._duration_ms(started_at_ns),
        )


    async def _fail_step_and_run(
        self,
        run: MergeReadinessRun,
        step: RuntimeStep,
        started_at_ns: int,
        error: RuntimeErrorInfo,
    ) -> MergeReadinessRun:
        failed_step = transition_step(
            step,
            StepStatus.FAILED,
            self._timestamp_clock(),
            duration_ms=self._duration_ms(started_at_ns),
            error=error,
        )
        run_with_failed_step = _replace_run(
            run,
            steps=(*run.steps[:-1], failed_step),
        )
        failed_run = transition_run(
            run_with_failed_step,
            RunStatus.FAILED,
            self._timestamp_clock(),
            error=error,
        )


        return await self._save(failed_run, PersistenceCheckpoint.RUN_FAILED)


    async def _persist_failed_step_and_run(
        self,
        run: MergeReadinessRun,
        step: RuntimeStep,
        started_at_ns: int,
        runtime_error: RuntimeErrorInfo,
        failure_category: FailureCategory,
        step_observation: SpanObservation,
    ) -> MergeReadinessRun:
        step_observation.set_attributes(
            **{"promptql.step.outcome": StepOutcome.FAILED.value}
        )
        step_observation.mark_error(failure_category)
        failed_run = await self._fail_step_and_run(
            run,
            step,
            started_at_ns,
            runtime_error,
        )
        self._record_terminal_step(
            failed_run,
            StepOutcome.FAILED,
            failure_category,
        )
        return failed_run


    def _record_terminal_step(
        self,
        run: MergeReadinessRun,
        outcome: StepOutcome,
        failure_category: FailureCategory | None = None,
    ) -> None:
        step = run.steps[-1]
        if step.duration_ms is None:
            return
        self._telemetry.record_terminal_step(
            run,
            step.name,
            step.duration_ms,
            outcome,
            failure_category,
        )


    def _record_terminal_run(
        self,
        run: MergeReadinessRun,
        observation: SpanObservation,
        failure_category: FailureCategory | None = None,
    ) -> MergeReadinessRun:
        attributes = {
            "promptql.run.status": run.status.value,
        }
        if run.result is not None:
            attributes["promptql.policy.decision"] = run.result.decision.value
        observation.set_attributes(**attributes)
        if failure_category is not None:
            observation.mark_error(failure_category)
        self._telemetry.record_terminal_workflow(run)
        return run


    @staticmethod
    def _persistence_failure_category(error: Exception) -> FailureCategory:
        if isinstance(error, RunStateConflictError):
            return FailureCategory.STATE_CONFLICT
        if isinstance(error, RunRecordInvalidError):
            return FailureCategory.RECORD_INVALID
        return FailureCategory.PERSISTENCE_UNAVAILABLE


    async def execute(self, request: ConnectorRequest) -> MergeReadinessRun:
        run = create_pending_run(request, sources=self._sources)
        return await self._execute_created_run(run, initial_snapshot_is_saved=False)

    async def create_persisted_run(
        self,
        request: ConnectorRequest,
    ) -> MergeReadinessRun:
        run = create_pending_run(request, sources=self._sources)
        return await self._save(run, PersistenceCheckpoint.RUN_CREATED)

    async def continue_persisted_run(
        self,
        run: MergeReadinessRun,
    ) -> MergeReadinessRun:
        return await self._execute_created_run(run, initial_snapshot_is_saved=True)

    async def _execute_created_run(
        self,
        run: MergeReadinessRun,
        *,
        initial_snapshot_is_saved: bool,
    ) -> MergeReadinessRun:
        with self._telemetry.observe_workflow(run) as workflow_observation:
            try:
                return await self._execute_workflow(
                    run,
                    workflow_observation,
                    initial_snapshot_is_saved=initial_snapshot_is_saved,
                )
            except (
                RunPersistenceError,
                RunStateConflictError,
                RunRecordInvalidError,
            ) as error:
                workflow_observation.mark_error(
                    self._persistence_failure_category(error)
                )
                raise
            except FixtureNotFoundError:
                workflow_observation.mark_error(
                    FailureCategory.FIXTURE_NOT_FOUND
                )
                raise
            except Exception:
                workflow_observation.mark_error(FailureCategory.SYSTEM_FAILURE)
                raise


    async def _execute_workflow(
        self,
        run: MergeReadinessRun,
        workflow_observation: SpanObservation,
        *,
        initial_snapshot_is_saved: bool,
    ) -> MergeReadinessRun:
        if not initial_snapshot_is_saved:
            run = await self._save(run, PersistenceCheckpoint.RUN_CREATED)
        run = await self._save(
            transition_run(
                run,
                RunStatus.RUNNING,
                self._timestamp_clock(),
            ),
            PersistenceCheckpoint.RUN_STARTED,
        )

        run, github_facts, workflow_must_stop = await self._fetch_github_facts(
            run,
            run.request,
            workflow_observation,
        )
        if workflow_must_stop:
            return run

        run, jira_facts, workflow_must_stop = await self._fetch_jira_facts(
            run,
            github_facts,
            workflow_observation,
        )
        if workflow_must_stop:
            return run

        return await self._evaluate_policy(
            run,
            github_facts,
            jira_facts,
            workflow_observation,
        )


    async def _fetch_github_facts(
        self,
        run: MergeReadinessRun,
        request: ConnectorRequest,
        workflow_observation: SpanObservation,
    ) -> tuple[MergeReadinessRun, GitHubPullRequest | None, bool]:
        run, github_step, github_started_ns = await self._start_step(
            run,
            WorkflowStepName.FETCH_GITHUB_FACTS,
        )
        with self._telemetry.observe_step(
            run,
            github_step.name,
        ) as github_observation:
            github_source = getattr(
                self._github_connector,
                "source",
                ConnectorSource.FAKE,
            )
            github_observation.set_attributes(
                **{
                    "promptql.connector.name": "github",
                    "promptql.connector.source": github_source.value,
                    "promptql.connector.operation": "get_pull_request",
                }
            )
            try:
                github_facts = await self._github_connector.get_pull_request(request)
                github_outcome = StepOutcome.COMPLETED
            except ConnectorUnavailableError:
                github_facts = None
                github_outcome = StepOutcome.UNAVAILABLE
            except FixtureNotFoundError:
                category = FailureCategory.FIXTURE_NOT_FOUND
                failed_run = await self._persist_failed_step_and_run(
                    run,
                    github_step,
                    github_started_ns,
                    RuntimeErrorInfo(
                        code=RuntimeErrorCode.FIXTURE_NOT_FOUND,
                        message="GitHub facts were not found for this request.",
                    ),
                    category,
                    github_observation,
                )
                self._record_terminal_run(
                    failed_run,
                    workflow_observation,
                    category,
                )
                raise
            except Exception:
                category = FailureCategory.CONNECTOR_FAILURE
                failed_run = await self._persist_failed_step_and_run(
                    run,
                    github_step,
                    github_started_ns,
                    RuntimeErrorInfo(
                        code=RuntimeErrorCode.CONNECTOR_EXECUTION_FAILED,
                        message="The GitHub connector step failed unexpectedly.",
                    ),
                    category,
                    github_observation,
                )
                terminal_run = self._record_terminal_run(
                    failed_run,
                    workflow_observation,
                    category,
                )
                return terminal_run, None, True
            github_observation.set_attributes(
                **{"promptql.step.outcome": github_outcome.value}
            )
        run = await self._complete_step(
            run,
            github_step,
            github_started_ns,
            github=github_facts,
        )
        self._record_terminal_step(run, github_outcome)
        return run, github_facts, False


    async def _fetch_jira_facts(
        self,
        run: MergeReadinessRun,
        github_facts: GitHubPullRequest | None,
        workflow_observation: SpanObservation,
    ) -> tuple[MergeReadinessRun, JiraIssue | None, bool]:
        run, jira_step, jira_started_ns = await self._start_step(
            run,
            WorkflowStepName.FETCH_JIRA_FACTS,
        )
        with self._telemetry.observe_step(
            run,
            jira_step.name,
        ) as jira_observation:
            jira_source = getattr(
                self._jira_connector,
                "source",
                ConnectorSource.FAKE,
            )
            jira_observation.set_attributes(
                **{
                    "promptql.connector.name": "jira",
                    "promptql.connector.source": jira_source.value,
                    "promptql.connector.operation": "get_issue",
                }
            )
            try:
                jira_key = None
                if github_facts is not None:
                    jira_key = github_facts.linked_jira_key

                if jira_key is None:
                    jira_facts = None
                    jira_outcome = StepOutcome.UNAVAILABLE
                else:
                    jira_facts = await self._jira_connector.get_issue(jira_key)
                    jira_outcome = StepOutcome.COMPLETED
            except ConnectorUnavailableError:
                jira_facts = None
                jira_outcome = StepOutcome.UNAVAILABLE
            except FixtureNotFoundError:
                category = FailureCategory.FIXTURE_NOT_FOUND
                failed_run = await self._persist_failed_step_and_run(
                    run,
                    jira_step,
                    jira_started_ns,
                    RuntimeErrorInfo(
                        code=RuntimeErrorCode.FIXTURE_NOT_FOUND,
                        message="Jira facts were not found for this request.",
                    ),
                    category,
                    jira_observation,
                )
                self._record_terminal_run(
                    failed_run,
                    workflow_observation,
                    category,
                )
                raise
            except Exception:
                category = FailureCategory.CONNECTOR_FAILURE
                failed_run = await self._persist_failed_step_and_run(
                    run,
                    jira_step,
                    jira_started_ns,
                    RuntimeErrorInfo(
                        code=RuntimeErrorCode.CONNECTOR_EXECUTION_FAILED,
                        message="The Jira connector step failed unexpectedly.",
                    ),
                    category,
                    jira_observation,
                )
                terminal_run = self._record_terminal_run(
                    failed_run,
                    workflow_observation,
                    category,
                )
                return terminal_run, None, True
            jira_observation.set_attributes(
                **{"promptql.step.outcome": jira_outcome.value}
            )
        run = await self._complete_step(
            run,
            jira_step,
            jira_started_ns,
            jira=jira_facts,
        )
        self._record_terminal_step(run, jira_outcome)
        return run, jira_facts, False


    async def _evaluate_policy(
        self,
        run: MergeReadinessRun,
        github_facts: GitHubPullRequest | None,
        jira_facts: JiraIssue | None,
        workflow_observation: SpanObservation,
    ) -> MergeReadinessRun:
        run, policy_step, policy_started_ns = await self._start_step(
            run,
            WorkflowStepName.EVALUATE_MERGE_READINESS,
        )
        with self._telemetry.observe_step(
            run,
            policy_step.name,
        ) as policy_observation:
            try:
                policy_result = self._policy_evaluator(
                    github_facts,
                    jira_facts,
                )
            except Exception:
                category = FailureCategory.POLICY_FAILURE
                failed_run = await self._persist_failed_step_and_run(
                    run,
                    policy_step,
                    policy_started_ns,
                    RuntimeErrorInfo(
                        code=RuntimeErrorCode.POLICY_EXECUTION_FAILED,
                        message=(
                            "The merge-readiness policy step failed unexpectedly."
                        ),
                    ),
                    category,
                    policy_observation,
                )
                return self._record_terminal_run(
                    failed_run,
                    workflow_observation,
                    category,
                )
            policy_observation.set_attributes(
                **{"promptql.step.outcome": StepOutcome.COMPLETED.value}
            )
        completed_policy_step = self._build_completed_step(
            policy_step,
            policy_started_ns,
        )
        run_with_completed_policy = _replace_run(
            run,
            steps=(*run.steps[:-1], completed_policy_step),
        )
        completed_run = transition_run(
            run_with_completed_policy,
            RunStatus.COMPLETED,
            self._timestamp_clock(),
            result=policy_result,
        )


        completed_run = await self._save(
            completed_run,
            PersistenceCheckpoint.RUN_COMPLETED,
        )
        self._record_terminal_step(completed_run, StepOutcome.COMPLETED)
        return self._record_terminal_run(
            completed_run,
            workflow_observation,
        )
