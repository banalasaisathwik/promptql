import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.connectors.incident_fakes import FakeIncidentSource
from app.connectors.github_code_fakes import FakeGitHubCodeEvidenceSource
from app.connectors.protocols import GitHubCodeEvidenceSource, IncidentSource, JiraConnector
from app.explanations import LLMClient, TypedLLMClient
from app.investigations import (
    AgentExecutor,
    ExecutionBudget,
    ExecutionStepStatus,
    InvestigationRequest,
    ToolInvoker,
)
from app.investigations.evidence_store import EvidenceStore
from app.investigations.planning import PlanValidator, TypedLLMPlanner
from app.investigations.code_diagnosis import (
    CodeContextBuilder,
    CodeDiagnosisError,
    CodeDiagnosisInput,
    DeterministicCodeFindingValidator,
    TypedLLMCodeDiagnoser,
    build_developer_recommendations,
)
from app.investigations.code_diagnosis.instructions import (
    CODE_DIAGNOSIS_PROMPT_VERSION,
)
from app.investigations.hypotheses import (
    DeterministicHypothesisValidator,
    GroundedTerminationReason,
    HypothesisGenerationError,
    HypothesisGenerationInput,
    TypedLLMHypothesisGenerator,
    build_hypothesis_generation_input,
    render_grounded_result,
)
from app.investigations.hypotheses.instructions import HYPOTHESIS_PROMPT_VERSION
from app.investigations.replanning import AdaptiveInvestigationRuntime, AdaptiveInvestigationState
from app.observability import (
    FailureCategory,
    InvestigationStage,
    InvestigationStageResult,
    NoOpRuntimeTelemetry,
    RuntimeTelemetry,
)
from app.runtime import (
    RunRepository,
    RunStatus,
    RuntimeErrorCode,
    RuntimeErrorInfo,
)
from app.runtime.investigation_models import (
    ExecutionState,
    InvestigationPlanningRoundSnapshot,
    InvestigationRun,
    InvestigationRuntimeSnapshot,
    InvestigationStepSnapshot,
    WorkingMemory,
)
from app.tools import InvestigationToolId, build_tool_adapters, build_tool_registry


INVESTIGATION_WORKFLOW_NAME = "investigation"
INVESTIGATION_WORKFLOW_VERSION = "2.19.2"
DEFAULT_TOOL_CALL_BUDGET = 10

# Tools the adaptive planner may select for this workflow. Named explicitly
# rather than passing the full registry, so adding a tool to the registry
# does not silently grant it to every investigation — a new tool_id must be
# added here as a deliberate decision.
ADAPTIVE_INVESTIGATION_ALLOWED_TOOL_IDS: tuple[InvestigationToolId, ...] = (
    InvestigationToolId.GET_COMMIT,
    InvestigationToolId.GET_DEPLOYMENTS,
    InvestigationToolId.GET_DIFF,
    InvestigationToolId.GET_FAILURE_LOCATION,
    InvestigationToolId.GET_INCIDENT,
    InvestigationToolId.GET_JIRA_ISSUE,
    InvestigationToolId.GET_PULL_REQUEST,
    InvestigationToolId.QUERY_TELEMETRY,
)


def _hypothesis_failure_diagnostics(
    generator: TypedLLMHypothesisGenerator,
    generation_input: HypothesisGenerationInput,
    error: HypothesisGenerationError,
) -> dict[str, object]:
    client = getattr(generator, "_client", None)
    provider = getattr(client, "provider", None)
    details = error.provider_details
    return {
        "event": "investigation.hypothesis.failed",
        "llm_provider": getattr(provider, "value", provider),
        "requested_model": getattr(client, "model", None),
        "prompt_version": HYPOTHESIS_PROMPT_VERSION,
        "facts_count": len(generation_input.facts),
        "missing_information_count": len(generation_input.missing_information),
        "exception_class": type(error).__name__,
        "failure_code": error.code.value,
        "failure_category": error.provider_failure_category,
        "http_status": details.http_status if details is not None else None,
        "provider_type": details.provider_type if details is not None else None,
        "provider_code": details.provider_code if details is not None else None,
        "provider_message": details.provider_message if details is not None else str(error),
        "failed_generation_present": (
            details.failed_generation_present if details is not None else False
        ),
        "failed_generation_length": (
            details.failed_generation_length if details is not None else None
        ),
        "local_schema_error": (
            error.code.value
            if error.code.value in {"invalid_response", "candidate_schema_invalid"}
            else None
        ),
    }


def _code_diagnosis_failure_diagnostics(
    diagnoser: TypedLLMCodeDiagnoser,
    diagnosis_input: CodeDiagnosisInput,
    error: CodeDiagnosisError,
) -> dict[str, object]:
    client = getattr(diagnoser, "_client", None)
    provider = getattr(client, "provider", None)
    details = error.provider_details
    return {
        "event": "investigation.code_diagnosis.failed",
        "llm_provider": getattr(provider, "value", provider),
        "requested_model": getattr(client, "model", None),
        "prompt_version": CODE_DIAGNOSIS_PROMPT_VERSION,
        "hypothesis_count": len(diagnosis_input.hypotheses),
        "facts_count": len(diagnosis_input.facts),
        "location_count": len(diagnosis_input.locations),
        "exception_class": type(error).__name__,
        "failure_code": error.code.value,
        "failure_category": error.provider_failure_category,
        "http_status": details.http_status if details is not None else None,
        "provider_type": details.provider_type if details is not None else None,
        "provider_code": details.provider_code if details is not None else None,
        "provider_message": details.provider_message if details is not None else str(error),
        "failed_generation_present": (
            details.failed_generation_present if details is not None else False
        ),
        "failed_generation_length": (
            details.failed_generation_length if details is not None else None
        ),
        "local_schema_error": (
            error.code.value
            if error.code.value in {"invalid_response", "candidate_schema_invalid"}
            else None
        ),
    }


class InvestigationWorkflowService:
    def __init__(
        self,
        repository: RunRepository,
        llm_client: LLMClient,
        planner_client: TypedLLMClient | None = None,
        *,
        code_diagnosis_client: TypedLLMClient | None = None,
        github_code_source: GitHubCodeEvidenceSource | None = None,
        incident_source: IncidentSource | None = None,
        jira_connector: JiraConnector | None = None,
        telemetry: RuntimeTelemetry | None = None,
    ) -> None:
        self._repository = repository
        self._llm_client = llm_client
        self._planner_client = planner_client or llm_client
        self._code_diagnosis_client = code_diagnosis_client or llm_client
        self._github_code_source = github_code_source or FakeGitHubCodeEvidenceSource()
        self._incident_source = incident_source or FakeIncidentSource()
        self._jira_connector = jira_connector
        self._telemetry = telemetry or NoOpRuntimeTelemetry()

    async def create_persisted_run(
        self, request: InvestigationRequest, run_id: UUID | None = None
    ) -> InvestigationRun:
        pending = InvestigationRun(
            run_id=run_id or uuid4(),
            workflow_name=INVESTIGATION_WORKFLOW_NAME,
            workflow_version=INVESTIGATION_WORKFLOW_VERSION,
            status=RunStatus.PENDING,
            started_at=None,
            completed_at=None,
            error=None,
            request=request,
            state=None,
            result=None,
        )
        self._repository.save(pending)
        return pending

    async def continue_persisted_run(self, pending: InvestigationRun) -> InvestigationRun:
        with self._telemetry.observe_investigation_stage(
            InvestigationStage.INVESTIGATION,
            pending.run_id,
        ) as investigation_observation:
            terminal = await self._continue_persisted_run(pending)
            state = terminal.state
            termination_reason = (
                terminal.result.termination_reason.value
                if terminal.result is not None
                else terminal.status.value
            )
            with self._telemetry.observe_investigation_stage(
                InvestigationStage.TERMINATION,
                pending.run_id,
            ) as termination_observation:
                self._telemetry.record_investigation_termination(
                    termination_observation,
                    planning_rounds=(
                        len(state.execution_state.rounds) if state is not None else 0
                    ),
                    tool_calls=(
                        state.execution_state.used_tool_calls if state is not None else 0
                    ),
                    termination_reason=termination_reason,
                )
                termination_observation.set_attributes(
                    **{"promptql.run.status": terminal.status.value}
                )
                if terminal.status is RunStatus.FAILED:
                    termination_observation.set_stage_result(
                        InvestigationStageResult.FAILED
                    )
                    termination_observation.mark_error(FailureCategory.SYSTEM_FAILURE)
            investigation_observation.set_attributes(
                **{"promptql.run.status": terminal.status.value}
            )
            if terminal.status is RunStatus.FAILED:
                investigation_observation.set_stage_result(
                    InvestigationStageResult.FAILED
                )
                investigation_observation.mark_error(FailureCategory.SYSTEM_FAILURE)
            return terminal

    async def _continue_persisted_run(self, pending: InvestigationRun) -> InvestigationRun:
        started_at = datetime.now(UTC)
        running = pending.model_copy(
            update={
                "status": RunStatus.RUNNING,
                "started_at": started_at,
                "state": self._empty_state(),
            }
        )
        self._repository.save(running)

        store = EvidenceStore()
        adapters = build_tool_adapters(
            self._github_code_source,
            self._incident_source,
            self._jira_connector,
            store,
        )
        registry = build_tool_registry(adapters)
        executor = AgentExecutor(
            registry,
            ToolInvoker(registry, adapters),
            store,
            telemetry=self._telemetry,
            run_id=pending.run_id,
        )


        async def save_planned_round(state, planned) -> None:
            snapshot = self._snapshot_from_adaptive(state, store)
            round_number = len(state.rounds) + 1
            self._telemetry.record_investigation_round(
                running.run_id, round_number, completed=False
            )
            pending_round = InvestigationPlanningRoundSnapshot(
                round_number=round_number,
                plan_id=f"round-{round_number}",
                plan_validation_status="accepted",
                planner_metadata=planned.metadata,
                steps=tuple(
                    InvestigationStepSnapshot(
                        step_id=step.step_id,
                        tool_id=step.tool_id,
                        status=ExecutionStepStatus.PENDING,
                        attempts=0,
                    )
                    for step in planned.plan.steps
                ),
            )
            self._repository.save(
                running.model_copy(
                    update={
                        "state": snapshot.model_copy(
                            update={
                                "execution_state": snapshot.execution_state.model_copy(
                                    update={
                                        "rounds": (
                                            *snapshot.execution_state.rounds,
                                            pending_round,
                                        )
                                    }
                                )
                            }
                        )
                    }
                )
            )

        async def save_completed_round(state) -> None:
            if state.rounds:
                self._telemetry.record_investigation_round(
                    running.run_id,
                    state.rounds[-1].round_number,
                    completed=True,
                )
            self._repository.save(
                running.model_copy(update={"state": self._snapshot_from_adaptive(state, store)})
            )

        try:
            adaptive_state = await AdaptiveInvestigationRuntime(
                TypedLLMPlanner(self._planner_client),
                PlanValidator(registry),
                executor,
                store,
                telemetry=self._telemetry,
                run_id=pending.run_id,
            ).investigate(
                running.request.question,
                tuple(
                    definition
                    for definition in registry.list()
                    if definition.tool_id in ADAPTIVE_INVESTIGATION_ALLOWED_TOOL_IDS
                ),
                budget=ExecutionBudget(max_tool_calls=DEFAULT_TOOL_CALL_BUDGET),
                request_context=running.request,
                on_round_planned=save_planned_round,
                on_round_completed=save_completed_round,
            )
        except asyncio.CancelledError:
            self._cancel(running)
            raise
        except Exception:
            return self._fail(
                running,
                started_at,
                RuntimeErrorCode.INVESTIGATION_RUNTIME_FAILURE,
            )
        try:
            return await self._complete_adaptive_run(
                running,
                adaptive_state,
                store,
            )
        except asyncio.CancelledError:
            self._cancel(running)
            raise
        except Exception:
            return self._fail(
                running,
                started_at,
                RuntimeErrorCode.INVESTIGATION_RUNTIME_FAILURE,
            )

    async def _complete_adaptive_run(
        self,
        running: InvestigationRun,
        adaptive_state: AdaptiveInvestigationState,
        store: EvidenceStore,
    ) -> InvestigationRun:
        state = self._snapshot_from_adaptive(adaptive_state, store)
        validated_hypotheses = ()
        rejected_hypothesis_count = 0
        hypothesis_metadata = None
        termination_reason = _grounded_reason(
            adaptive_state.continuation_reason.value
        )
        hypothesis_input = build_hypothesis_generation_input(
            running.request,
            AdaptiveInvestigationState(
                rounds=(),
                evidence=adaptive_state.evidence,
                facts=adaptive_state.facts,
                missing_information=adaptive_state.missing_information,
                action_history=adaptive_state.action_history,
                remaining_tool_calls=adaptive_state.remaining_tool_calls,
                continuation_reason=adaptive_state.continuation_reason,
            ),
            telemetry=self._telemetry,
            run_id=running.run_id,
        )
        if adaptive_state.facts:
            hypothesis_generator = TypedLLMHypothesisGenerator(self._llm_client)
            try:
                with self._telemetry.observe_investigation_stage(
                    InvestigationStage.HYPOTHESIS_GENERATION,
                    running.run_id,
                    task="hypothesis_generation",
                    provider=self._llm_client.provider.value,
                    requested_model=self._llm_client.model,
                    prompt_version=HYPOTHESIS_PROMPT_VERSION,
                ) as generation_observation:
                    try:
                        generated = await hypothesis_generator.generate(hypothesis_input)
                    except HypothesisGenerationError as error:
                        generation_observation.set_stage_result(
                            InvestigationStageResult.FAILED
                        )
                        generation_observation.mark_error(
                            FailureCategory.LLM_PROVIDER_FAILURE
                            if error.code.value == "provider_failure"
                            else FailureCategory.LLM_INVALID_OUTPUT
                        )
                        raise
                    _set_generation_span_attributes(
                        generation_observation,
                        generated.metadata,
                    )
                    self._telemetry.record_llm_token_usage(
                        running.run_id,
                        "hypothesis",
                        generated.metadata.token_usage,
                    )
                hypothesis_metadata = generated.metadata
            except HypothesisGenerationError as error:
                diagnostics = _hypothesis_failure_diagnostics(
                    hypothesis_generator,
                    hypothesis_input,
                    error,
                )
                event = diagnostics.pop("event")
                self._telemetry.record_investigation_diagnostic_failure(
                    running.run_id,
                    event,
                    **diagnostics,
                )
                termination_reason = (
                    GroundedTerminationReason.HYPOTHESIS_GENERATION_FAILURE
                )
            else:
                with self._telemetry.observe_investigation_stage(
                    InvestigationStage.HYPOTHESIS_VALIDATION,
                    running.run_id,
                ) as validation_observation:
                    validation_result = DeterministicHypothesisValidator().validate(
                        generated.candidates,
                        adaptive_state.facts,
                    )
                    validated_hypotheses = validation_result.accepted_hypotheses
                    rejected_hypothesis_count = len(
                        validation_result.rejected_candidates
                    )
                    if generated.candidates and not validated_hypotheses:
                        validation_observation.set_stage_result(
                            InvestigationStageResult.REJECTED
                        )

        validated_code_findings = ()
        rejected_code_finding_count = 0
        code_diagnosis_metadata = None
        developer_recommendations = ()
        if validated_hypotheses:
            evidence = store.get_many(adaptive_state.evidence)
            diagnosis_input = CodeContextBuilder().build(
                running.request,
                validated_hypotheses,
                adaptive_state.facts,
                evidence,
            )
            code_diagnoser = TypedLLMCodeDiagnoser(self._code_diagnosis_client)
            try:
                with self._telemetry.observe_investigation_stage(
                    InvestigationStage.CODE_DIAGNOSIS,
                    running.run_id,
                    task="code_diagnosis",
                    provider=self._code_diagnosis_client.provider.value,
                    requested_model=self._code_diagnosis_client.model,
                    prompt_version=CODE_DIAGNOSIS_PROMPT_VERSION,
                ) as diagnosis_observation:
                    try:
                        generated_findings = await code_diagnoser.generate(
                            diagnosis_input
                        )
                    except CodeDiagnosisError as error:
                        diagnosis_observation.set_stage_result(
                            InvestigationStageResult.FAILED
                        )
                        diagnosis_observation.mark_error(
                            FailureCategory.LLM_PROVIDER_FAILURE
                            if error.code.value == "provider_failure"
                            else FailureCategory.LLM_INVALID_OUTPUT
                        )
                        raise
                    _set_generation_span_attributes(
                        diagnosis_observation,
                        generated_findings.metadata,
                    )
                    self._telemetry.record_llm_token_usage(
                        running.run_id,
                        "code_diagnosis",
                        generated_findings.metadata.token_usage,
                    )
                code_diagnosis_metadata = generated_findings.metadata
            except CodeDiagnosisError as error:
                diagnostics = _code_diagnosis_failure_diagnostics(
                    code_diagnoser,
                    diagnosis_input,
                    error,
                )
                event = diagnostics.pop("event")
                self._telemetry.record_investigation_diagnostic_failure(
                    running.run_id,
                    event,
                    **diagnostics,
                )
                termination_reason = GroundedTerminationReason.CODE_DIAGNOSIS_FAILURE
            else:
                with self._telemetry.observe_investigation_stage(
                    InvestigationStage.CODE_VALIDATION,
                    running.run_id,
                ) as validation_observation:
                    finding_validation = DeterministicCodeFindingValidator().validate(
                        generated_findings.candidates,
                        validated_hypotheses,
                        adaptive_state.facts,
                        evidence,
                    )
                    validated_code_findings = finding_validation.accepted_findings
                    rejected_code_finding_count = len(
                        finding_validation.rejected_candidates
                    )
                    if generated_findings.candidates and not validated_code_findings:
                        validation_observation.set_stage_result(
                            InvestigationStageResult.REJECTED
                        )
                developer_recommendations = build_developer_recommendations(
                    validated_code_findings
                )

        state = state.model_copy(
            update={
                "working_memory": state.working_memory.model_copy(
                    update={
                        "validated_hypotheses": validated_hypotheses,
                        "validated_code_findings": validated_code_findings,
                        "developer_recommendations": developer_recommendations,
                    }
                ),
                "execution_state": state.execution_state.model_copy(
                    update={
                        "rejected_hypothesis_count": rejected_hypothesis_count,
                        "hypothesis_generation_metadata": hypothesis_metadata,
                        "rejected_code_finding_count": rejected_code_finding_count,
                        "code_diagnosis_metadata": code_diagnosis_metadata,
                        "termination_reason": adaptive_state.continuation_reason.value,
                    }
                ),
            }
        )
        with self._telemetry.observe_investigation_stage(
            InvestigationStage.RENDER,
            running.run_id,
        ):
            grounded_result = render_grounded_result(
                state.working_memory.facts,
                validated_hypotheses,
                state.working_memory.missing_information,
                termination_reason,
                validated_code_findings,
                developer_recommendations,
                state.working_memory.evidence,
            )
        completed = running.model_copy(
            update={
                "status": RunStatus.COMPLETED,
                "completed_at": datetime.now(UTC),
                "state": state,
                "result": grounded_result,
            }
        )
        self._repository.save(completed)
        return completed

    def _fail(
        self,
        running: InvestigationRun,
        started_at: datetime,
        code: RuntimeErrorCode,
    ) -> InvestigationRun:
        messages = {
            RuntimeErrorCode.INVESTIGATION_PLAN_INVALID: (
                "The investigation could not validate its execution plan."
            ),
            RuntimeErrorCode.INVESTIGATION_RUNTIME_FAILURE: (
                "The investigation runtime failed before it could complete."
            ),
        }
        failed = running.model_copy(
            update={
                "status": RunStatus.FAILED,
                "completed_at": datetime.now(UTC),
                "error": RuntimeErrorInfo(
                    code=code,
                    message=messages[code],
                ),
                "state": None,
            }
        )
        self._repository.save(failed)
        return failed

    def _cancel(self, running: InvestigationRun) -> InvestigationRun:
        # Round-boundary callbacks already persisted the latest snapshot
        # durably (save_planned_round/save_completed_round); re-read it so
        # cancellation keeps that progress instead of reverting to the empty
        # snapshot `running` was constructed with at the start of this run.
        latest = self._repository.get(running.run_id)
        base = latest if isinstance(latest, InvestigationRun) else running
        cancelled = base.model_copy(
            update={
                "status": RunStatus.CANCELLED,
                "completed_at": datetime.now(UTC),
            }
        )
        self._repository.save(cancelled)
        return cancelled

    @staticmethod
    def _empty_state() -> InvestigationRuntimeSnapshot:
        return InvestigationRuntimeSnapshot(
            working_memory=WorkingMemory(),
            execution_state=ExecutionState(
                max_tool_calls=DEFAULT_TOOL_CALL_BUDGET,
                used_tool_calls=0,
                remaining_tool_calls=DEFAULT_TOOL_CALL_BUDGET,
            ),
        )

    @staticmethod
    def _snapshot_from_adaptive(
        state: AdaptiveInvestigationState, store: EvidenceStore
    ) -> InvestigationRuntimeSnapshot:
        rounds = tuple(
            InvestigationPlanningRoundSnapshot(
                round_number=round.round_number,
                plan_id=round.plan_id,
                plan_validation_status="accepted",
                planner_metadata=round.planner_metadata,
                steps=tuple(
                    InvestigationStepSnapshot(
                        step_id=step.step_id,
                        tool_id=next(item.tool_id for item in round.execution.validated_plan.plan.steps if item.step_id == step.step_id),
                        status=step.status,
                        attempts=step.attempts,
                        failure_code=step.failure.code.value if step.failure else None,
                        failure_message=step.failure.message if step.failure else None,
                        block_reason=step.block_reason,
                    ) for step in round.execution.step_states
                ),
                evidence_delta_ids=round.evidence_delta_ids,
                fact_delta_ids=round.fact_delta_ids,
                completed=True,
            ) for round in state.rounds
        )
        return InvestigationRuntimeSnapshot(
            working_memory=WorkingMemory(
                evidence=state.evidence,
                evidence_content=store.get_many(state.evidence),
                facts=state.facts,
                missing_information=state.missing_information,
                action_history=state.action_history,
            ),
            execution_state=ExecutionState(
                rounds=rounds,
                max_tool_calls=DEFAULT_TOOL_CALL_BUDGET,
                used_tool_calls=DEFAULT_TOOL_CALL_BUDGET - state.remaining_tool_calls,
                remaining_tool_calls=state.remaining_tool_calls,
                termination_reason=state.continuation_reason.value,
            ),
        )


def _grounded_reason(reason: str) -> GroundedTerminationReason:
    return {
        "completed": GroundedTerminationReason.COMPLETED,
        "tool_call_budget_exhausted": GroundedTerminationReason.BUDGET_EXHAUSTED,
        "no_progress": GroundedTerminationReason.NO_PROGRESS,
        "max_planning_rounds": GroundedTerminationReason.PLANNING_LIMIT_REACHED,
        "planner_failure": GroundedTerminationReason.PLANNER_FAILURE,
        "plan_validation_failure": GroundedTerminationReason.PLAN_VALIDATION_FAILURE,
    }.get(reason, GroundedTerminationReason.COMPLETED)


def _set_generation_span_attributes(observation, metadata) -> None:
    attributes = {
        "promptql.llm.provider": metadata.provider,
        "promptql.llm.requested_model": metadata.requested_model or metadata.model,
    }
    if metadata.resolved_model is not None:
        attributes["promptql.llm.resolved_model"] = metadata.resolved_model
        attributes["langfuse.observation.model.name"] = metadata.resolved_model
        attributes["gen_ai.response.model"] = metadata.resolved_model
    if metadata.token_usage is not None:
        attributes["promptql.llm.input_tokens"] = metadata.token_usage.input_tokens
        attributes["promptql.llm.output_tokens"] = metadata.token_usage.output_tokens
        attributes["gen_ai.usage.input_tokens"] = metadata.token_usage.input_tokens
        attributes["gen_ai.usage.output_tokens"] = metadata.token_usage.output_tokens
        if metadata.token_usage.total_tokens is not None:
            attributes["promptql.llm.total_tokens"] = metadata.token_usage.total_tokens
    observation.set_attributes(**attributes)
