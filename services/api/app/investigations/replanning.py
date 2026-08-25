import json
import logging
from collections.abc import Awaitable, Callable, Iterable, Iterator
from contextlib import contextmanager
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from app.connectors.models import ContractModel, NonEmptyString
from app.investigations.execution import (
    AgentExecutor,
    ExecutionBudget,
    InvestigationExecutionState,
)
from app.investigations.evidence_store import EvidenceStore
from app.investigations.fact_derivation import derive_facts
from app.investigations.models import FactSet, InvestigationIdentifier, InvestigationRequest, MissingInformation
from app.investigations.planning import (
    ActionSummary,
    ContextBuilder,
    InvestigationPlannerError,
    MAX_ADAPTIVE_PLAN_STEPS,
    PlanValidator,
    PlannedInvestigation,
    PlannerInput,
    PlannerMetadata,
    PlannerToolDefinition,
    PlannerToolInputField,
    TypedLLMPlanner,
)
from app.investigations.planning.instructions import PLANNER_PROMPT_VERSION
from app.observability.contracts import (
    FailureCategory,
    InvestigationStage,
    InvestigationStageResult,
)
from app.observability.runtime_telemetry import RuntimeTelemetry
from app.tools.models import ToolDefinition, ToolOutcome


MAX_PLANNING_ROUNDS = 3
MAX_NO_PROGRESS_ROUNDS = 1


_PLANNER_DIAGNOSTIC_LOGGER = logging.getLogger("promptql.runtime")


class ContinuationReason(StrEnum):
    COMPLETE = "complete"
    MAX_PLANNING_ROUNDS = "max_planning_rounds"
    TOOL_CALL_BUDGET_EXHAUSTED = "tool_call_budget_exhausted"
    NO_PROGRESS = "no_progress"
    PLANNER_FAILURE = "planner_failure"
    PLAN_VALIDATION_FAILURE = "plan_validation_failure"


class PlanningRound(ContractModel):
    round_number: int = Field(ge=1)
    plan_id: str
    planner_metadata: PlannerMetadata
    execution: InvestigationExecutionState
    evidence_delta_ids: tuple[str, ...] = ()
    fact_delta_ids: tuple[str, ...] = ()


class AdaptiveInvestigationState(ContractModel):
    rounds: tuple[PlanningRound, ...]
    evidence: tuple[InvestigationIdentifier, ...]
    facts: FactSet
    missing_information: tuple[MissingInformation, ...]
    action_history: tuple[ActionSummary, ...]
    remaining_tool_calls: int = Field(ge=0)
    continuation_reason: ContinuationReason


def _tool_context(definition: ToolDefinition) -> PlannerToolDefinition:
    schema = definition.input_schema
    required = frozenset(schema.get("required", ()))
    return PlannerToolDefinition(
        tool_id=definition.tool_id,
        description=definition.description,
        input_fields=tuple(
            PlannerToolInputField(name=name, required=name in required)
            for name in sorted(schema.get("properties", {}))
        ),
        input_schema=schema,
        output_schema=definition.plan_output_model.model_json_schema(),
    )


def _planner_failure_diagnostics(
    planner: TypedLLMPlanner,
    planner_input: PlannerInput,
    error: InvestigationPlannerError,
) -> dict[str, object]:
    client = getattr(planner, "_client", None)
    provider = getattr(client, "provider", None)
    model = getattr(client, "model", None)
    provider_details = error.provider_details
    return {
        "event": "investigation.planner.failed",
        "round": planner_input.planning_round,
        "provider": getattr(provider, "value", provider),
        "requested_model": model,
        "prompt_version": PLANNER_PROMPT_VERSION,
        "facts_count": len(planner_input.facts),
        "evidence_count": len(planner_input.evidence),
        "missing_information_count": len(planner_input.missing_information),
        "action_history_count": len(planner_input.action_history),
        "remaining_tool_calls": planner_input.remaining_tool_calls,
        "allowed_tool_ids": [str(tool.tool_id) for tool in planner_input.allowed_tools],
        "exception_class": type(error).__name__,
        "http_status": (
            provider_details.http_status if provider_details is not None else None
        ),
        "provider_type": (
            provider_details.provider_type if provider_details is not None else None
        ),
        "provider_code": (
            provider_details.provider_code if provider_details is not None else None
        ),
        "provider_message": (
            provider_details.provider_message
            if provider_details is not None and provider_details.provider_message
            else str(error)
        ),
        "failed_generation_present": (
            provider_details.failed_generation_present
            if provider_details is not None
            else False
        ),
        "failed_generation_length": (
            provider_details.failed_generation_length
            if provider_details is not None
            else None
        ),
        "planner_failure_code": error.code.value,
        "provider_failure_category": error.provider_failure_category,
        "local_schema_error": (
            error.code.value
            if error.code.value in {"invalid_response", "plan_schema_invalid"}
            else None
        ),
    }


class AdaptiveInvestigationRuntime:
    def __init__(
        self,
        planner: TypedLLMPlanner,
        validator: PlanValidator,
        executor: AgentExecutor,
        store: EvidenceStore,
        *,
        telemetry: RuntimeTelemetry | None = None,
        run_id: UUID | None = None,
    ) -> None:
        self._planner = planner
        self._validator = validator
        self._executor = executor
        self._store = store
        self._telemetry = telemetry
        self._run_id = run_id

    async def investigate(
        self,
        investigation_goal: NonEmptyString,
        allowed_tools: Iterable[ToolDefinition],
        *,
        budget: ExecutionBudget,
        initial_evidence: tuple[InvestigationIdentifier, ...] = (),
        initial_missing_information: tuple[MissingInformation, ...] = (),
        request_context: InvestigationRequest | None = None,
        on_round_planned: Callable[
            [AdaptiveInvestigationState, PlannedInvestigation], Awaitable[None]
        ]
        | None = None,
        on_round_completed: Callable[[AdaptiveInvestigationState], Awaitable[None]] | None = None,
    ) -> AdaptiveInvestigationState:
        definitions = tuple(sorted(allowed_tools, key=lambda item: item.tool_id))
        evidence = initial_evidence
        facts: FactSet = derive_facts(self._store.get_many(initial_evidence))
        missing_information = initial_missing_information
        history: list[ActionSummary] = []
        rounds: list[PlanningRound] = []
        remaining = budget.max_tool_calls
        no_progress_rounds = 0

        for round_number in range(1, MAX_PLANNING_ROUNDS + 1):
            if remaining == 0:
                return self._state(
                    rounds,
                    evidence,
                    facts,
                    missing_information,
                    history,
                    remaining,
                    ContinuationReason.TOOL_CALL_BUDGET_EXHAUSTED,
                )
            with self._observe_stage(
                InvestigationStage.PLANNING_ROUND,
                round_number=round_number,
            ) as round_observation:
                planner_input = ContextBuilder().build(
                    investigation_goal,
                    facts,
                    missing_information,
                    self._store.get_many(evidence),
                    definitions,
                    action_history=tuple(history),
                    remaining_tool_calls=remaining,
                    planning_round=round_number,
                    max_planning_rounds=MAX_PLANNING_ROUNDS,
                    request_context=request_context,
                )
                planner_client = getattr(self._planner, "_client", None)
                provider = getattr(getattr(planner_client, "provider", None), "value", None)
                with self._observe_stage(
                    InvestigationStage.PLANNER,
                    round_number=round_number,
                    task="planning",
                    provider=provider,
                    requested_model=getattr(planner_client, "model", None),
                    prompt_version=PLANNER_PROMPT_VERSION,
                ) as planner_observation:
                    try:
                        planned = await self._planner.plan(planner_input)
                    except InvestigationPlannerError as error:
                        if planner_observation is not None:
                            planner_observation.set_stage_result(
                                InvestigationStageResult.FAILED
                            )
                            planner_observation.mark_error(
                                FailureCategory.LLM_PROVIDER_FAILURE
                                if error.code.value == "provider_failure"
                                else FailureCategory.LLM_INVALID_OUTPUT
                            )
                        if round_observation is not None:
                            round_observation.set_stage_result(
                                InvestigationStageResult.FAILED
                            )


                        _PLANNER_DIAGNOSTIC_LOGGER.error(
                            json.dumps(
                                _planner_failure_diagnostics(
                                    self._planner,
                                    planner_input,
                                    error,
                                ),
                                separators=(",", ":"),
                                sort_keys=True,
                            )
                        )
                        return self._state(
                            rounds,
                            evidence,
                            facts,
                            missing_information,
                            history,
                            remaining,
                            ContinuationReason.PLANNER_FAILURE,
                        )
                    _set_generation_attributes(planner_observation, planned.metadata)

                with self._observe_stage(
                    InvestigationStage.PLAN_VALIDATION,
                    round_number=round_number,
                ) as validation_observation:
                    if len(planned.plan.steps) > MAX_ADAPTIVE_PLAN_STEPS:
                        _mark_rejected(validation_observation)
                        _mark_rejected(round_observation)
                        return self._state(
                            rounds,
                            evidence,
                            facts,
                            missing_information,
                            history,
                            remaining,
                            ContinuationReason.PLAN_VALIDATION_FAILURE,
                        )
                    validation = self._validator.validate(planned.plan, definitions)
                    if not validation.valid:
                        _mark_rejected(validation_observation)
                        _mark_rejected(round_observation)
                        return self._state(
                            rounds,
                            evidence,
                            facts,
                            missing_information,
                            history,
                            remaining,
                            ContinuationReason.PLAN_VALIDATION_FAILURE,
                        )
                if on_round_planned is not None:
                    await on_round_planned(
                        self._state(
                            rounds,
                            evidence,
                            facts,
                            missing_information,
                            history,
                            remaining,
                            ContinuationReason.COMPLETE,
                        ),
                        planned,
                    )
                before_evidence = set(evidence)
                before_facts = {item.fact_id for item in facts}


                execution = await self._executor.execute(
                    validation.validated_plan,
                    budget=ExecutionBudget(max_tool_calls=remaining),
                    initial_evidence=evidence,
                    round_number=round_number,
                )
            evidence, facts = execution.evidence, execution.facts
            missing_information = self._merge_missing_information(
                missing_information,
                execution.missing_information,
            )
            remaining = execution.budget.remaining_tool_calls
            evidence_delta = tuple(sorted(set(evidence) - before_evidence))
            fact_delta = tuple(sorted({item.fact_id for item in facts} - before_facts))
            rounds.append(
                PlanningRound(
                    round_number=round_number,
                    plan_id=f"round-{round_number}",
                    planner_metadata=planned.metadata,
                    execution=execution,
                    evidence_delta_ids=evidence_delta,
                    fact_delta_ids=fact_delta,
                )
            )
            new_facts_by_id = {
                fact.fact_id: fact
                for fact in facts
                if fact.fact_id in fact_delta
            }
            for step in execution.step_states:
                if step.attempts == 0:
                    continue
                tool_id = next(item.tool_id for item in planned.plan.steps if item.step_id == step.step_id)
                result_evidence_ids = (
                    set(step.tool_result.evidence_ids) if step.tool_result else set()
                )


                history.append(
                    ActionSummary(
                        tool_id=tool_id,
                        outcome=(
                            step.tool_result.outcome
                            if step.tool_result
                            else ToolOutcome.FAILED
                        ),
                        produced_new_evidence=bool(
                            result_evidence_ids.intersection(evidence_delta)
                        ),
                        produced_new_facts=any(
                            result_evidence_ids.intersection(
                                fact.evidence_reference_ids
                            )
                            for fact in new_facts_by_id.values()
                        ),
                    )
                )
            if on_round_completed is not None:
                await on_round_completed(
                    self._state(
                        rounds,
                        evidence,
                        facts,
                        missing_information,
                        history,
                        remaining,
                        ContinuationReason.COMPLETE,
                    )
                )


            no_progress_rounds = no_progress_rounds + 1 if not evidence_delta and not fact_delta else 0
            if no_progress_rounds >= MAX_NO_PROGRESS_ROUNDS:
                return self._state(
                    rounds,
                    evidence,
                    facts,
                    missing_information,
                    history,
                    remaining,
                    ContinuationReason.NO_PROGRESS,
                )

        return self._state(
            rounds,
            evidence,
            facts,
            missing_information,
            history,
            remaining,
            ContinuationReason.MAX_PLANNING_ROUNDS,
        )

    @staticmethod
    def _state(
        rounds,
        evidence,
        facts,
        missing_information,
        history,
        remaining,
        reason,
    ):
        return AdaptiveInvestigationState(
            rounds=tuple(rounds),
            evidence=evidence,
            facts=facts,
            missing_information=missing_information,
            action_history=tuple(history),
            remaining_tool_calls=remaining,
            continuation_reason=reason,
        )

    @staticmethod
    def _merge_missing_information(
        accumulated: tuple[MissingInformation, ...],
        incoming: tuple[MissingInformation, ...],
    ) -> tuple[MissingInformation, ...]:
        items_by_id = {
            item.missing_information_id: item for item in accumulated
        }
        for item in incoming:
            items_by_id.setdefault(item.missing_information_id, item)
        return tuple(items_by_id.values())

    @contextmanager
    def _observe_stage(
        self,
        stage: InvestigationStage,
        *,
        round_number: int | None = None,
        task: str | None = None,
        provider: str | None = None,
        requested_model: str | None = None,
        prompt_version: str | None = None,
    ) -> Iterator[object | None]:
        if self._telemetry is None or self._run_id is None:
            yield None
            return
        with self._telemetry.observe_investigation_stage(
            stage,
            self._run_id,
            round_number=round_number,
            task=task,
            provider=provider,
            requested_model=requested_model,
            prompt_version=prompt_version,
        ) as observation:
            yield observation


def _set_generation_attributes(observation, metadata: PlannerMetadata) -> None:
    if observation is None:
        return
    attributes = {}
    if metadata.resolved_model is not None:
        attributes["promptql.llm.resolved_model"] = metadata.resolved_model
        attributes["langfuse.observation.model.name"] = metadata.resolved_model
        attributes["gen_ai.response.model"] = metadata.resolved_model
    if metadata.token_usage is not None:
        attributes.update(
            {
                "promptql.llm.input_tokens": metadata.token_usage.input_tokens,
                "promptql.llm.output_tokens": metadata.token_usage.output_tokens,
                "gen_ai.usage.input_tokens": metadata.token_usage.input_tokens,
                "gen_ai.usage.output_tokens": metadata.token_usage.output_tokens,
            }
        )
        if metadata.token_usage.total_tokens is not None:
            attributes["promptql.llm.total_tokens"] = metadata.token_usage.total_tokens
    observation.set_attributes(**attributes)


def _mark_rejected(observation) -> None:
    if observation is None:
        return
    observation.set_stage_result(InvestigationStageResult.REJECTED)
    observation.mark_error(FailureCategory.LLM_VALIDATION_FAILURE)
