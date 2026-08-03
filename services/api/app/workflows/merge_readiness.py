pass

from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter_ns
from typing import Protocol

from app.connectors.errors import ConnectorUnavailableError, FixtureNotFoundError
from app.connectors.models import ConnectorRequest, GitHubPullRequest, JiraIssue
from app.policy import evaluate_merge_readiness
from app.policy.models import MergeReadinessResult
from app.runtime import (
    MergeReadinessRun,
    RunRepository,
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


class GitHubConnector(Protocol):
    pass

    def get_pull_request(self, request: ConnectorRequest) -> GitHubPullRequest: ...


class JiraConnector(Protocol):
    pass

    def get_issue_for_pull_request(self, request: ConnectorRequest) -> JiraIssue: ...


PolicyEvaluator = Callable[
    [GitHubPullRequest | None, JiraIssue | None],
    MergeReadinessResult,
]
TimestampClock = Callable[[], datetime]
DurationClock = Callable[[], int]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _replace_run(run: MergeReadinessRun, **updates) -> MergeReadinessRun:
    pass

    values = run.model_dump()
    values.update(updates)
    return MergeReadinessRun.model_validate(values)


class MergeReadinessWorkflowService:
    pass

    def __init__(
        self,
        github_connector: GitHubConnector,
        jira_connector: JiraConnector,
        run_repository: RunRepository,
        policy_evaluator: PolicyEvaluator = evaluate_merge_readiness,
        timestamp_clock: TimestampClock = _utc_now,
        duration_clock: DurationClock = perf_counter_ns,
    ) -> None:
        self._github_connector = github_connector
        self._jira_connector = jira_connector
        self._run_repository = run_repository
        self._policy_evaluator = policy_evaluator
        self._timestamp_clock = timestamp_clock
        self._duration_clock = duration_clock

    def _save(self, run: MergeReadinessRun) -> MergeReadinessRun:
        self._run_repository.save(run)
        return run

    def _start_step(
        self,
        run: MergeReadinessRun,
        name: WorkflowStepName,
    ) -> tuple[MergeReadinessRun, RuntimeStep, int]:
        pass

        pending_step = create_pending_step(name)
        run = self._save(_replace_run(run, steps=(*run.steps, pending_step)))

        running_step = transition_step(
            pending_step,
            StepStatus.RUNNING,
            self._timestamp_clock(),
        )
        run = self._save(
            _replace_run(run, steps=(*run.steps[:-1], running_step))
        )
        return run, running_step, self._duration_clock()

    def _duration_ms(self, started_at_ns: int) -> int:
        elapsed_ns = max(0, self._duration_clock() - started_at_ns)
        return elapsed_ns // 1_000_000

    def _complete_step(
        self,
        run: MergeReadinessRun,
        step: RuntimeStep,
        started_at_ns: int,
        **run_updates,
    ) -> MergeReadinessRun:
        completed_step = self._build_completed_step(step, started_at_ns)
        return self._save(
            _replace_run(
                run,
                steps=(*run.steps[:-1], completed_step),
                **run_updates,
            )
        )

    def _build_completed_step(
        self,
        step: RuntimeStep,
        started_at_ns: int,
    ) -> RuntimeStep:
        pass

        return transition_step(
            step,
            StepStatus.COMPLETED,
            self._timestamp_clock(),
            duration_ms=self._duration_ms(started_at_ns),
        )

    def _fail_step_and_run(
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



        return self._save(failed_run)

    def execute(self, request: ConnectorRequest) -> MergeReadinessRun:
        pass

        run = self._save(create_pending_run(request))
        run = self._save(
            transition_run(
                run,
                RunStatus.RUNNING,
                self._timestamp_clock(),
            )
        )

        run, github_step, github_started_ns = self._start_step(
            run,
            WorkflowStepName.FETCH_GITHUB_FACTS,
        )
        try:
            github = self._github_connector.get_pull_request(request)
        except ConnectorUnavailableError:
            github = None
        except FixtureNotFoundError:
            self._fail_step_and_run(
                run,
                github_step,
                github_started_ns,
                RuntimeErrorInfo(
                    code=RuntimeErrorCode.FIXTURE_NOT_FOUND,
                    message="GitHub facts were not found for this request.",
                ),
            )
            raise
        except Exception:
            return self._fail_step_and_run(
                run,
                github_step,
                github_started_ns,
                RuntimeErrorInfo(
                    code=RuntimeErrorCode.CONNECTOR_EXECUTION_FAILED,
                    message="The GitHub connector step failed unexpectedly.",
                ),
            )
        run = self._complete_step(
            run,
            github_step,
            github_started_ns,
            github=github,
        )

        run, jira_step, jira_started_ns = self._start_step(
            run,
            WorkflowStepName.FETCH_JIRA_FACTS,
        )
        try:
            jira = self._jira_connector.get_issue_for_pull_request(request)
        except ConnectorUnavailableError:
            jira = None
        except FixtureNotFoundError:
            self._fail_step_and_run(
                run,
                jira_step,
                jira_started_ns,
                RuntimeErrorInfo(
                    code=RuntimeErrorCode.FIXTURE_NOT_FOUND,
                    message="Jira facts were not found for this request.",
                ),
            )
            raise
        except Exception:
            return self._fail_step_and_run(
                run,
                jira_step,
                jira_started_ns,
                RuntimeErrorInfo(
                    code=RuntimeErrorCode.CONNECTOR_EXECUTION_FAILED,
                    message="The Jira connector step failed unexpectedly.",
                ),
            )
        run = self._complete_step(
            run,
            jira_step,
            jira_started_ns,
            jira=jira,
        )

        run, policy_step, policy_started_ns = self._start_step(
            run,
            WorkflowStepName.EVALUATE_MERGE_READINESS,
        )
        try:
            result = self._policy_evaluator(github, jira)
        except Exception:
            return self._fail_step_and_run(
                run,
                policy_step,
                policy_started_ns,
                RuntimeErrorInfo(
                    code=RuntimeErrorCode.POLICY_EXECUTION_FAILED,
                    message="The merge-readiness policy step failed unexpectedly.",
                ),
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
            result=result,
        )


        return self._save(completed_run)
