"""User-facing V2 investigation workflow built on the existing run repository."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.connectors.errors import ConnectorUnavailableError, FixtureNotFoundError
from app.connectors.incident_fakes import FakeIncidentSource
from app.connectors.models import FailureLocationEvidenceRequest
from app.connectors.github_code_fakes import FakeGitHubCodeEvidenceSource
from app.connectors.protocols import GitHubCodeEvidenceSource, IncidentSource, JiraConnector
from app.explanations import LLMClient, TypedLLMClient
from app.investigations import (
    AgentExecutor,
    ExecutionBudget,
    ExecutionStepStatus,
    InvestigationPlan,
    InvestigationRequest,
    Literal,
    PlanArgument,
    PlanStep,
    ToolInvoker,
    MissingInformation,
    MissingInformationKind,
)
from app.investigations.fact_derivation import derive_facts
from app.investigations.planning import PlanValidator, TypedLLMPlanner
from app.investigations.hypotheses import (
    DeterministicHypothesisValidator,
    GroundedTerminationReason,
    HypothesisGenerationError,
    TypedLLMHypothesisGenerator,
    build_hypothesis_generation_input,
    render_grounded_result,
)
from app.investigations.execution import InvestigationExecutionState
from app.investigations.replanning import AdaptiveInvestigationRuntime, AdaptiveInvestigationState, ContinuationReason
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
from app.tools import InvestigationToolId
from app.tools import build_tool_adapters, build_tool_registry


INVESTIGATION_WORKFLOW_NAME = "investigation"
INVESTIGATION_WORKFLOW_VERSION = "2.19"
DEFAULT_TOOL_CALL_BUDGET = 10


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
        github_code_source: GitHubCodeEvidenceSource | None = None,
        incident_source: IncidentSource | None = None,
        jira_connector: JiraConnector | None = None,
    ) -> None:
        self._repository = repository
        self._llm_client = llm_client
        self._planner_client = planner_client or llm_client
        self._github_code_source = github_code_source or FakeGitHubCodeEvidenceSource()
        self._incident_source = incident_source or FakeIncidentSource()
        self._jira_connector = jira_connector

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
                    update={"state": snapshot.model_copy(update={"rounds": (*snapshot.rounds, pending_round)})}
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
            adaptive_state = await AdaptiveInvestigationRuntime(
                TypedLLMPlanner(self._planner_client), PlanValidator(registry), executor
            ).investigate(
                running.request.incident_summary,
                registry.list(),
                budget=ExecutionBudget(max_tool_calls=DEFAULT_TOOL_CALL_BUDGET),
                on_round_planned=save_planned_round,
                on_round_completed=save_completed_round,
            )
        except Exception:
            return self._fail(
                running,
                started_at,
                RuntimeErrorCode.INVESTIGATION_RUNTIME_FAILURE,
            )
        # Compatibility boundary: failure-location evidence remains a bounded
        # post-processing lookup in Pass A, rather than becoming a planner tool.
        adaptive_state = await self._add_failure_location_to_adaptive_state(
            adaptive_state, running.request
        )
        # Execution state is converted to a compact API snapshot before any
        # hypothesis generation, so Facts remain the source of truth for both
        # observability and final rendering.
        state = self._snapshot_from_adaptive(adaptive_state)

        validated_hypotheses = ()
        rejected_count = 0
        termination_reason = _grounded_reason(adaptive_state.continuation_reason.value)
        try:
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
            generated = await TypedLLMHypothesisGenerator(self._llm_client).generate(
                hypothesis_input
            )
            validation_result = DeterministicHypothesisValidator().validate(
                generated.candidates, adaptive_state.facts
            )
            validated_hypotheses = validation_result.accepted_hypotheses
            rejected_count = len(validation_result.rejected_candidates)
        except HypothesisGenerationError:
            termination_reason = GroundedTerminationReason.PROVIDER_FAILURE

        state = state.model_copy(
            update={
                "validated_hypotheses": validated_hypotheses,
                "rejected_hypothesis_count": rejected_count,
                # The snapshot reports the adaptive runtime's actual stopping
                # condition; the rendered result may separately report that
                # hypothesis generation was unavailable.
                "termination_reason": adaptive_state.continuation_reason.value,
            }
        )
        grounded_result = render_grounded_result(
            state.facts,
            validated_hypotheses,
            state.missing_information,
            termination_reason,
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

    async def _complete_without_evidence(
        self, running: InvestigationRun, started_at: datetime
    ) -> InvestigationRun:
        state = self._empty_state().model_copy(
            update={
                "termination_reason": GroundedTerminationReason.COMPLETED.value,
            }
        )
        result = render_grounded_result(
            (), (), (), GroundedTerminationReason.COMPLETED
        )
        completed = running.model_copy(
            update={
                "status": RunStatus.COMPLETED,
                "completed_at": datetime.now(UTC),
                "state": state,
                "result": result,
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
    def _pending_state(plan: InvestigationPlan) -> InvestigationRuntimeSnapshot:
        return InvestigationRuntimeSnapshot(
            rounds=(
                InvestigationPlanningRoundSnapshot(
                    round_number=1,
                    plan_id="round-1",
                    plan_validation_status="accepted",
                    steps=tuple(
                        InvestigationStepSnapshot(
                            step_id=step.step_id,
                            tool_id=step.tool_id,
                            status=ExecutionStepStatus.PENDING,
                            attempts=0,
                        )
                        for step in plan.steps
                    ),
                    completed=False,
                ),
            ),
            max_tool_calls=DEFAULT_TOOL_CALL_BUDGET,
            used_tool_calls=0,
            remaining_tool_calls=DEFAULT_TOOL_CALL_BUDGET,
        )

    async def _add_failure_location_evidence(
        self,
        execution: InvestigationExecutionState,
        request: InvestigationRequest,
    ) -> InvestigationExecutionState:
        if request.incident_reference is None:
            return execution
        try:
            failure_location = await self._incident_source.get_failure_location_evidence(
                FailureLocationEvidenceRequest(
                    incident_reference=request.incident_reference
                )
            )
        except (ConnectorUnavailableError, FixtureNotFoundError):
            return execution.model_copy(
                update={
                    "missing_information": (
                        *execution.missing_information,
                        MissingInformation(
                            missing_information_id="missing:failure-location",
                            kind=MissingInformationKind.SOURCE_DATA_UNAVAILABLE,
                            detail="The incident failure location was unavailable.",
                        ),
                    )
                }
            )
        evidence_by_id = {item.evidence_id: item for item in execution.evidence}
        evidence_by_id.setdefault(failure_location.evidence_id, failure_location)
        evidence = tuple(evidence_by_id.values())
        return execution.model_copy(update={"evidence": evidence, "facts": derive_facts(evidence)})

    async def _add_failure_location_to_adaptive_state(
        self,
        state: AdaptiveInvestigationState,
        request: InvestigationRequest,
    ) -> AdaptiveInvestigationState:
        if request.incident_reference is None:
            return state
        try:
            failure_location = await self._incident_source.get_failure_location_evidence(
                FailureLocationEvidenceRequest(incident_reference=request.incident_reference)
            )
        except (ConnectorUnavailableError, FixtureNotFoundError):
            return state.model_copy(update={"missing_information": (*state.missing_information, MissingInformation(missing_information_id="missing:failure-location", kind=MissingInformationKind.SOURCE_DATA_UNAVAILABLE, detail="The incident failure location was unavailable."))})
        evidence_by_id = {item.evidence_id: item for item in state.evidence}
        evidence_by_id.setdefault(failure_location.evidence_id, failure_location)
        evidence = tuple(evidence_by_id.values())
        return state.model_copy(update={"evidence": evidence, "facts": derive_facts(evidence)})

    @staticmethod
    def _snapshot_from_execution(
        execution: InvestigationExecutionState,
        plan: InvestigationPlan,
    ) -> InvestigationRuntimeSnapshot:
        tools_by_step = {step.step_id: step.tool_id for step in plan.steps}
        steps = tuple(
            InvestigationStepSnapshot(
                step_id=step.step_id,
                tool_id=tools_by_step[step.step_id],
                status=step.status,
                attempts=step.attempts,
                failure_code=step.failure.code.value if step.failure else None,
                failure_message=step.failure.message if step.failure else None,
                block_reason=step.block_reason,
            )
            for step in execution.step_states
        )
        round_snapshot = InvestigationPlanningRoundSnapshot(
            round_number=1,
            plan_id="round-1",
            plan_validation_status="accepted",
            steps=steps,
            evidence_delta_ids=tuple(item.evidence_id for item in execution.evidence),
            fact_delta_ids=tuple(item.fact_id for item in execution.facts),
            completed=True,
        )
        return InvestigationRuntimeSnapshot(
            rounds=(round_snapshot,),
            evidence=execution.evidence,
            facts=execution.facts,
            missing_information=execution.missing_information,
            max_tool_calls=execution.budget.max_tool_calls,
            used_tool_calls=execution.budget.used_tool_calls,
            remaining_tool_calls=execution.budget.remaining_tool_calls,
        )

    @staticmethod
    def _snapshot_from_adaptive(state: AdaptiveInvestigationState) -> InvestigationRuntimeSnapshot:
        rounds = tuple(
            InvestigationPlanningRoundSnapshot(
                round_number=round.round_number,
                plan_id=round.plan_id,
                plan_validation_status="accepted",
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
        "planner_failure": GroundedTerminationReason.PROVIDER_FAILURE,
        "plan_validation_failure": GroundedTerminationReason.PLAN_VALIDATION_FAILURE,
    }.get(reason, GroundedTerminationReason.COMPLETED)


def _literal(name: str, value: object) -> PlanArgument:
    return PlanArgument(name=name, value=Literal(value=value))


def _build_static_plan(request: InvestigationRequest) -> InvestigationPlan | None:
    steps: list[PlanStep] = []
    if request.incident_reference:
        steps.append(
            PlanStep(
                step_id="s1",
                tool_id=InvestigationToolId.GET_INCIDENT,
                arguments=(_literal("incident_reference", request.incident_reference),),
                reason="Collect the incident record.",
            )
        )
    if request.deployment_reference and len(steps) < 5:
        steps.append(
            PlanStep(
                step_id=f"s{len(steps) + 1}",
                tool_id=InvestigationToolId.GET_DEPLOYMENTS,
                arguments=(_literal("deployment_reference", request.deployment_reference),),
                reason="Collect deployment timing and revision evidence.",
            )
        )
    if request.telemetry_window and len(steps) < 5:
        steps.append(
            PlanStep(
                step_id=f"s{len(steps) + 1}",
                tool_id=InvestigationToolId.QUERY_TELEMETRY,
                arguments=tuple(
                    _literal(name, value)
                    for name, value in request.telemetry_window.model_dump().items()
                ),
                reason="Collect bounded telemetry evidence.",
            )
        )
    if request.pull_request_number and len(steps) < 5:
        steps.append(
            PlanStep(
                step_id=f"s{len(steps) + 1}",
                tool_id=InvestigationToolId.GET_PULL_REQUEST,
                arguments=(
                    _literal("repository_owner", request.repository_owner),
                    _literal("repository_name", request.repository_name),
                    _literal("pr_number", request.pull_request_number),
                ),
                reason="Collect pull-request evidence.",
            )
        )
    if request.pull_request_number and len(steps) < 5:
        steps.append(
            PlanStep(
                step_id=f"s{len(steps) + 1}",
                tool_id=InvestigationToolId.GET_DIFF,
                arguments=(
                    _literal("repository_owner", request.repository_owner),
                    _literal("repository_name", request.repository_name),
                    _literal("pr_number", request.pull_request_number),
                ),
                reason="Collect changed-file evidence.",
            )
        )
    return InvestigationPlan(steps=tuple(steps)) if steps else None
