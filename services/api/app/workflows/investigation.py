"""User-facing V2 investigation workflow built on the existing run repository."""

import json
import logging
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
    InvestigationPlanningRoundSnapshot,
    InvestigationRun,
    InvestigationRuntimeSnapshot,
    InvestigationStepSnapshot,
)
from app.tools import build_tool_adapters, build_tool_registry


INVESTIGATION_WORKFLOW_NAME = "investigation"
INVESTIGATION_WORKFLOW_VERSION = "2.19.2"
DEFAULT_TOOL_CALL_BUDGET = 10
_HYPOTHESIS_DIAGNOSTIC_LOGGER = logging.getLogger("promptql.runtime")
_CODE_DIAGNOSIS_LOGGER = logging.getLogger("promptql.runtime")


# PURPOSE: Make the final probabilistic boundary as observable as planning.
#
# FLOW: Read already-sanitized error metadata -> combine it with counts and
# prompt/model identity -> return a JSON-safe event for the runtime logger.
#
# SECURITY: Facts, missing-information details, prompts, provider responses,
# headers, and credentials are deliberately absent from the returned mapping.
def _hypothesis_failure_diagnostics(
    generator: TypedLLMHypothesisGenerator,
    generation_input: HypothesisGenerationInput,
    error: HypothesisGenerationError,
) -> dict[str, object]:
    """Allowlist failure metadata without retaining Facts, prompts, or responses."""

    client = getattr(generator, "_client", None)
    provider = getattr(client, "provider", None)
    details = error.provider_details
    return {
        "event": "investigation.hypothesis.failed",
        "provider": getattr(provider, "value", provider),
        "requested_model": getattr(client, "model", None),
        "prompt_version": HYPOTHESIS_PROMPT_VERSION,
        "facts_count": len(generation_input.facts),
        "missing_information_count": len(generation_input.missing_information),
        "exception_class": type(error).__name__,
        "failure_code": error.code.value,
        "provider_failure_category": error.provider_failure_category,
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
    """Allowlist code-diagnosis failure metadata without code or candidate text."""

    client = getattr(diagnoser, "_client", None)
    provider = getattr(client, "provider", None)
    details = error.provider_details
    return {
        "event": "investigation.code_diagnosis.failed",
        "provider": getattr(provider, "value", provider),
        "requested_model": getattr(client, "model", None),
        "prompt_version": CODE_DIAGNOSIS_PROMPT_VERSION,
        "hypothesis_count": len(diagnosis_input.hypotheses),
        "facts_count": len(diagnosis_input.facts),
        "location_count": len(diagnosis_input.locations),
        "exception_class": type(error).__name__,
        "failure_code": error.code.value,
        "provider_failure_category": error.provider_failure_category,
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
    # PURPOSE: Adapt the V2 executor and hypothesis boundary to the existing
    # durable run lifecycle used by the V1 live dashboard.
    #
    # FLOW: Save pending -> save running/plan snapshots -> execute validated
    # read-only steps -> validate hypothesis candidates against Facts -> render
    # the grounded result -> save one terminal snapshot.
    #
    # WHY: Keeping persistence and execution orchestration here lets the router
    # remain an HTTP boundary and keeps the existing polling path authoritative.
    """Create durable V2 snapshots while reusing the existing polling boundary."""

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
        # FLOW: The root span surrounds the real persisted workflow. Termination
        # is emitted only after a terminal snapshot exists, so its round/tool
        # counts describe backend truth rather than an optimistic in-flight view.
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
                    planning_rounds=len(state.rounds) if state is not None else 0,
                    tool_calls=state.used_tool_calls if state is not None else 0,
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
        # The first running save gives a refresh a real lifecycle state; the
        # later plan save exposes pending tool steps before external calls begin.
        started_at = datetime.now(UTC)
        running = pending.model_copy(
            update={
                "status": RunStatus.RUNNING,
                "started_at": started_at,
                "state": self._empty_state(),
            }
        )
        self._repository.save(running)

        adapters = build_tool_adapters(
            self._github_code_source,
            self._incident_source,
            self._jira_connector,
        )
        registry = build_tool_registry(adapters)
        executor = AgentExecutor(
            registry,
            ToolInvoker(registry, adapters),
            telemetry=self._telemetry,
            run_id=pending.run_id,
        )

        # These callbacks are invoked only at round boundaries. Keeping saves
        # here avoids changing AgentExecutor just to expose per-step polling.
        async def save_planned_round(state, planned) -> None:
            snapshot = self._snapshot_from_adaptive(state)
            round_number = len(state.rounds) + 1
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
                            update={"rounds": (*snapshot.rounds, pending_round)}
                        )
                    }
                )
            )

        async def save_completed_round(state) -> None:
            self._repository.save(
                running.model_copy(update={"state": self._snapshot_from_adaptive(state)})
            )

        try:
            # The planner may propose work, but the existing adaptive runtime
            # remains the authority for validation, shared budget accounting,
            # round termination, and accumulated Evidence/Facts.
            # The question and its typed request context cross unchanged. This
            # layer does not infer intent or invent tool arguments.
            adaptive_state = await AdaptiveInvestigationRuntime(
                TypedLLMPlanner(self._planner_client),
                PlanValidator(registry),
                executor,
                telemetry=self._telemetry,
                run_id=pending.run_id,
            ).investigate(
                running.request.question,
                registry.list(),
                budget=ExecutionBudget(max_tool_calls=DEFAULT_TOOL_CALL_BUDGET),
                request_context=running.request,
                on_round_planned=save_planned_round,
                on_round_completed=save_completed_round,
            )
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
            )
        except Exception:
            # Any programming/invariant failure after evidence collection must
            # still move the durable run out of RUNNING. Known provider failures
            # are handled inside the completion path and retain partial truth.
            return self._fail(
                running,
                started_at,
                RuntimeErrorCode.INVESTIGATION_RUNTIME_FAILURE,
            )

    async def _complete_adaptive_run(
        self,
        running: InvestigationRun,
        adaptive_state: AdaptiveInvestigationState,
    ) -> InvestigationRun:
        # Execution state is converted to a compact API snapshot before any
        # probabilistic synthesis, so Facts remain authoritative throughout.
        state = self._snapshot_from_adaptive(adaptive_state)
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
        )
        if adaptive_state.facts:
            # An empty Fact set has no admissible causal support. Skipping the
            # provider call is cheaper and keeps abstention deterministic.
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
                hypothesis_metadata = generated.metadata
            except HypothesisGenerationError as error:
                _HYPOTHESIS_DIAGNOSTIC_LOGGER.error(
                    json.dumps(
                        _hypothesis_failure_diagnostics(
                            hypothesis_generator,
                            hypothesis_input,
                            error,
                        ),
                        separators=(",", ":"),
                        sort_keys=True,
                    )
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
            # FLOW: A validated hypothesis unlocks a minimized provider call,
            # but not an authoritative finding. Only the deterministic validator
            # can copy an observed location into persisted domain state.
            diagnosis_input = CodeContextBuilder().build(
                running.request,
                validated_hypotheses,
                adaptive_state.facts,
                adaptive_state.evidence,
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
                code_diagnosis_metadata = generated_findings.metadata
            except CodeDiagnosisError as error:
                # WATCH OUT: This is a partial-success result. Evidence and the
                # grounded hypothesis stay useful even though the optional,
                # later diagnosis stage could not produce accepted structure.
                _CODE_DIAGNOSIS_LOGGER.error(
                    json.dumps(
                        _code_diagnosis_failure_diagnostics(
                            code_diagnoser,
                            diagnosis_input,
                            error,
                        ),
                        separators=(",", ":"),
                        sort_keys=True,
                    )
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
                        adaptive_state.evidence,
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
                "validated_hypotheses": validated_hypotheses,
                "rejected_hypothesis_count": rejected_hypothesis_count,
                "hypothesis_generation_metadata": hypothesis_metadata,
                "validated_code_findings": validated_code_findings,
                "rejected_code_finding_count": rejected_code_finding_count,
                "code_diagnosis_metadata": code_diagnosis_metadata,
                "developer_recommendations": developer_recommendations,
                # This field reports the adaptive runtime stop. The final result
                # separately reports a later synthesis-stage provider failure.
                "termination_reason": adaptive_state.continuation_reason.value,
            }
        )
        with self._telemetry.observe_investigation_stage(
            InvestigationStage.RENDER,
            running.run_id,
        ):
            grounded_result = render_grounded_result(
                state.facts,
                validated_hypotheses,
                state.missing_information,
                termination_reason,
                validated_code_findings,
                developer_recommendations,
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

    @staticmethod
    def _empty_state() -> InvestigationRuntimeSnapshot:
        return InvestigationRuntimeSnapshot(
            max_tool_calls=DEFAULT_TOOL_CALL_BUDGET,
            used_tool_calls=0,
            remaining_tool_calls=DEFAULT_TOOL_CALL_BUDGET,
        )

    @staticmethod
    def _snapshot_from_adaptive(state: AdaptiveInvestigationState) -> InvestigationRuntimeSnapshot:
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
            rounds=rounds,
            evidence=state.evidence,
            facts=state.facts,
            missing_information=state.missing_information,
            action_history=state.action_history,
            max_tool_calls=DEFAULT_TOOL_CALL_BUDGET,
            used_tool_calls=DEFAULT_TOOL_CALL_BUDGET - state.remaining_tool_calls,
            remaining_tool_calls=state.remaining_tool_calls,
            termination_reason=state.continuation_reason.value,
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
    # Provider-reported usage and resolved identity are observability facts, not
    # evidence about the incident. Missing values stay absent; cost is never
    # guessed from local configuration.
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
