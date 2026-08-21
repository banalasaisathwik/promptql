"""Bounded, round-boundary orchestration for V2 investigation replanning."""

import json
import logging
from collections.abc import Awaitable, Callable, Iterable
from enum import StrEnum

from pydantic import Field

from app.connectors.models import ContractModel, NonEmptyString
from app.investigations.execution import AgentExecutor, ExecutionBudget, InvestigationExecutionState
from app.investigations.models import Evidence, FactSet, InvestigationRequest, MissingInformation
from app.investigations.planning import (
    ActionSummary,
    ContextBuilder,
    InvestigationPlannerError,
    MAX_ADAPTIVE_PLAN_STEPS,
    PlanValidator,
    PlannedInvestigation,
    PlannerInput,
    PlannerToolDefinition,
    PlannerToolInputField,
    TypedLLMPlanner,
)
from app.investigations.planning.instructions import PLANNER_PROMPT_VERSION
from app.tools.models import ToolDefinition, ToolOutcome


MAX_PLANNING_ROUNDS = 3
MAX_NO_PROGRESS_ROUNDS = 1
# Reuse the configured runtime logger. A sibling logger would not inherit its
# handler because the runtime logger intentionally does not propagate upward.
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
    execution: InvestigationExecutionState
    evidence_delta_ids: tuple[str, ...] = ()
    fact_delta_ids: tuple[str, ...] = ()


class AdaptiveInvestigationState(ContractModel):
    rounds: tuple[PlanningRound, ...]
    evidence: tuple[Evidence, ...]
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


# PURPOSE: Preserve enough safe context to distinguish planner transport,
# provider, and local-schema failures after the typed planner has translated an
# exception. The compact result is observability data, never runtime state.
#
# SECURITY: Counts and stable tool IDs are allowed; the investigation goal,
# Evidence summaries, prompt, provider response, headers, and credentials stay
# outside this record.
def _planner_failure_diagnostics(
    planner: TypedLLMPlanner,
    planner_input: PlannerInput,
    error: InvestigationPlannerError,
) -> dict[str, object]:
    """Return only bounded metadata needed to debug a failed planner call."""
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
    # PURPOSE: Coordinate several short, independently validated plans while
    # preserving one investigation's accumulated state and global call limit.
    #
    # FLOW: Build safe planner context -> validate its proposal -> let the
    # existing executor finish the entire round -> compare ID sets -> either
    # stop deterministically or begin the next round. It never interprets the
    # semantic meaning of an Evidence or Fact.
    #
    # DESIGN: This orchestration layer keeps LLM strategy separate from runtime
    # safety, much like a TypeScript service coordinates existing components
    # instead of duplicating their internal execution logic.
    """Plan, validate, and execute short plans without mid-plan interruption."""

    def __init__(self, planner: TypedLLMPlanner, validator: PlanValidator, executor: AgentExecutor) -> None:
        self._planner = planner
        self._validator = validator
        self._executor = executor

    async def investigate(
        self,
        investigation_goal: NonEmptyString,
        allowed_tools: Iterable[ToolDefinition],
        *,
        budget: ExecutionBudget,
        initial_evidence: tuple[Evidence, ...] = (),
        initial_missing_information: tuple[MissingInformation, ...] = (),
        request_context: InvestigationRequest | None = None,
        on_round_planned: Callable[[AdaptiveInvestigationState, PlannedInvestigation], Awaitable[None]] | None = None,
        on_round_completed: Callable[[AdaptiveInvestigationState], Awaitable[None]] | None = None,
    ) -> AdaptiveInvestigationState:
        definitions = tuple(sorted(allowed_tools, key=lambda item: item.tool_id))
        evidence = initial_evidence
        facts: FactSet = ()
        missing_information = initial_missing_information
        history: list[ActionSummary] = []
        rounds: list[PlanningRound] = []
        remaining = budget.max_tool_calls
        no_progress_rounds = 0

        for round_number in range(1, MAX_PLANNING_ROUNDS + 1):
            if remaining == 0:
                return self._state(rounds, evidence, facts, missing_information, history, remaining, ContinuationReason.TOOL_CALL_BUDGET_EXHAUSTED)
            planner_input = ContextBuilder().build(
                investigation_goal,
                facts,
                missing_information,
                evidence,
                definitions,
                action_history=tuple(history),
                remaining_tool_calls=remaining,
                planning_round=round_number,
                max_planning_rounds=MAX_PLANNING_ROUNDS,
                request_context=request_context,
            )
            try:
                planned = await self._planner.plan(planner_input)
            except InvestigationPlannerError as error:
                # Log counts and stable identifiers, never the goal, compacted
                # Evidence, prompt text, headers, provider body, or credentials.
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
                return self._state(rounds, evidence, facts, missing_information, history, remaining, ContinuationReason.PLANNER_FAILURE)
            # V2.7 still permits five-step standalone plans; adaptive runtime
            # deliberately accepts only the shorter V2.16 horizon.
            if len(planned.plan.steps) > MAX_ADAPTIVE_PLAN_STEPS:
                return self._state(rounds, evidence, facts, missing_information, history, remaining, ContinuationReason.PLAN_VALIDATION_FAILURE)
            validation = self._validator.validate(planned.plan, definitions)
            if not validation.valid:
                return self._state(rounds, evidence, facts, missing_information, history, remaining, ContinuationReason.PLAN_VALIDATION_FAILURE)
            if on_round_planned is not None:
                await on_round_planned(
                    self._state(rounds, evidence, facts, missing_information, history, remaining, ContinuationReason.COMPLETE),
                    planned,
                )
            before_evidence = {item.evidence_id for item in evidence}
            before_facts = {item.fact_id for item in facts}
            # The executor receives only the remaining global allowance. Its
            # existing per-attempt accounting therefore remains authoritative
            # across rounds, including retries.
            execution = await self._executor.execute(validation.validated_plan, budget=ExecutionBudget(max_tool_calls=remaining), initial_evidence=evidence)
            evidence, facts = execution.evidence, execution.facts
            missing_information = tuple((*missing_information, *execution.missing_information))
            remaining = execution.budget.remaining_tool_calls
            evidence_delta = tuple(sorted({item.evidence_id for item in evidence} - before_evidence))
            fact_delta = tuple(sorted({item.fact_id for item in facts} - before_facts))
            rounds.append(PlanningRound(round_number=round_number, plan_id=f"round-{round_number}", execution=execution, evidence_delta_ids=evidence_delta, fact_delta_ids=fact_delta))
            for step in execution.step_states:
                if step.attempts == 0:
                    continue
                tool_id = next(item.tool_id for item in planned.plan.steps if item.step_id == step.step_id)
                result_evidence_ids = {
                    item.evidence_id for item in (step.tool_result.evidence if step.tool_result else ())
                }
                history.append(ActionSummary(tool_id=tool_id, outcome=step.tool_result.outcome if step.tool_result else ToolOutcome.FAILED, produced_new_evidence=bool(result_evidence_ids.intersection(evidence_delta)), produced_new_facts=bool(fact_delta and result_evidence_ids)))
            if on_round_completed is not None:
                await on_round_completed(
                    self._state(rounds, evidence, facts, missing_information, history, remaining, ContinuationReason.COMPLETE)
                )
            # ID deltas mean state changed; they deliberately do not rank the
            # information or introduce a provider/domain-specific signal rule.
            no_progress_rounds = no_progress_rounds + 1 if not evidence_delta and not fact_delta else 0
            if no_progress_rounds >= MAX_NO_PROGRESS_ROUNDS:
                return self._state(rounds, evidence, facts, missing_information, history, remaining, ContinuationReason.NO_PROGRESS)

        return self._state(rounds, evidence, facts, missing_information, history, remaining, ContinuationReason.MAX_PLANNING_ROUNDS)

    @staticmethod
    def _state(rounds, evidence, facts, missing_information, history, remaining, reason):
        return AdaptiveInvestigationState(rounds=tuple(rounds), evidence=evidence, facts=facts, missing_information=missing_information, action_history=tuple(history), remaining_tool_calls=remaining, continuation_reason=reason)
