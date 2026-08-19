"""Deterministic V2.9-V2.12 interpreter for an accepted investigation plan."""

import asyncio
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Awaitable, Callable

from pydantic import Field

from app.connectors.models import ContractModel, NonEmptyString
from app.investigations import Evidence, FactSet, MissingInformation, MissingInformationKind
from app.investigations.baseline import ToolInvoker
from app.investigations.fact_derivation import derive_facts
from app.investigations.planning import Literal, PlanStep, StepOutputRef, ValidatedPlan
from app.investigations.planning.models import PlanStepIdentifier
from app.tools import ToolFailure, ToolOutcome, ToolRegistry, ToolResult


class ExecutionStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class ExecutionBlockReason(StrEnum):
    DEPENDENCY_FAILED = "dependency_failed"
    RUNTIME_OUTPUT_UNAVAILABLE = "runtime_output_unavailable"
    BUDGET_EXHAUSTED = "budget_exhausted"


class ExecutionTerminationReason(StrEnum):
    COMPLETED = "completed"
    BUDGET_EXHAUSTED = "budget_exhausted"


class ExecutionBudget(ContractModel):
    max_tool_calls: int = Field(ge=0, le=100)


# PURPOSE: Keep the owner-approved attempt cap and delay formula as explicit
# validated runtime input instead of burying retry numbers in loop control flow.
#
# FLOW: After failed attempt 1 it returns 1 second; after failed attempt 2 it
# returns 2 seconds. The executor calls it only after a typed retryable failure.
#
# DESIGN: This pure model is the Python equivalent of a small immutable policy
# object; it keeps timing testable without coupling it to a provider SDK.
class RetryPolicy(ContractModel):
    # V2.12 deliberately caps this initial policy at the owner-confirmed three
    # total attempts. Later tuning needs a new policy decision and evidence.
    max_attempts: int = Field(default=3, ge=1, le=3)
    initial_backoff_seconds: float = Field(default=1.0, gt=0, le=60)
    backoff_multiplier: float = Field(default=2.0, ge=2, le=2)

    def delay_after_failure(self, completed_attempts: int) -> float:
        return self.initial_backoff_seconds * (
            self.backoff_multiplier ** (completed_attempts - 1)
        )


class BudgetState(ContractModel):
    # PURPOSE: Keep mutable execution accounting separate from the caller's
    # immutable budget policy. This is the sequential equivalent of reserving a
    # resource before an external operation; concurrent workers need atomics later.
    max_tool_calls: int = Field(ge=0, le=100)
    used_tool_calls: int = Field(default=0, ge=0)

    @property
    def remaining_tool_calls(self) -> int:
        # `@property` exposes derived state like a read-only field to callers,
        # while storing only the two values needed to reproduce the calculation.
        return self.max_tool_calls - self.used_tool_calls

    def consume_attempt(self) -> "BudgetState":
        if self.remaining_tool_calls <= 0:
            raise ValueError("tool-call budget is exhausted")
        return self.model_copy(update={"used_tool_calls": self.used_tool_calls + 1})


class ExecutionStepState(ContractModel):
    step_id: PlanStepIdentifier
    status: ExecutionStepStatus
    attempts: int = Field(default=0, ge=0)
    tool_result: ToolResult | None = None
    failure: ToolFailure | None = None
    block_reason: ExecutionBlockReason | None = None


class InvestigationExecutionState(ContractModel):
    # The accepted plan is retained as input context. The executor never edits it.
    validated_plan: ValidatedPlan
    step_states: tuple[ExecutionStepState, ...]
    runtime_outputs: dict[PlanStepIdentifier, dict[str, Any]] = Field(default_factory=dict)
    evidence: tuple[Evidence, ...] = ()
    facts: FactSet = ()
    missing_information: tuple[MissingInformation, ...] = ()
    budget: BudgetState
    termination_reason: ExecutionTerminationReason


class AgentExecutor:
    # PURPOSE: Interpret a statically validated plan, like a small program, while
    # leaving tool choice and graph legality to the planner and validator.
    #
    # FLOW: Check dependency/output readiness -> validate typed arguments ->
    # reserve budget -> invoke once -> retry only a typed transient failure ->
    # merge evidence -> recompute deterministic facts. No LLM participates.
    #
    # DESIGN: Keeping this separate from ToolRegistry preserves the registry as
    # metadata and gives later runtime policies one clear enforcement point.
    """Interpret one accepted plan sequentially without calling a planner."""

    def __init__(
        self,
        registry: ToolRegistry,
        invoker: ToolInvoker,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._registry = registry
        self._invoker = invoker
        self._sleep = sleep

    async def execute(
        self,
        validated_plan: ValidatedPlan,
        *,
        budget: ExecutionBudget,
        initial_evidence: tuple[Evidence, ...] = (),
        retry_policy: RetryPolicy | None = None,
    ) -> InvestigationExecutionState:
        evidence = self._deduplicate_evidence(initial_evidence)
        facts = derive_facts(evidence)
        steps_by_id = {step.step_id: step for step in validated_plan.plan.steps}
        step_states = {
            step_id: ExecutionStepState(step_id=step_id, status=ExecutionStepStatus.PENDING)
            for step_id in validated_plan.topological_step_ids
        }
        runtime_outputs: dict[str, dict[str, Any]] = {}
        missing_information: list[MissingInformation] = []
        budget_state = BudgetState(max_tool_calls=budget.max_tool_calls)
        termination_reason = ExecutionTerminationReason.COMPLETED
        resolved_retry_policy = retry_policy or RetryPolicy()

        for position, step_id in enumerate(validated_plan.topological_step_ids):
            step = steps_by_id[step_id]
            # Exhaustion is global policy, not a failure of this particular step:
            # remaining work is never invoked, even if its dependencies succeeded.
            if budget_state.remaining_tool_calls == 0:
                termination_reason = ExecutionTerminationReason.BUDGET_EXHAUSTED
                for remaining_step_id in validated_plan.topological_step_ids[position:]:
                    step_states[remaining_step_id] = ExecutionStepState(
                        step_id=remaining_step_id,
                        status=ExecutionStepStatus.BLOCKED,
                        block_reason=ExecutionBlockReason.BUDGET_EXHAUSTED,
                    )
                break
            dependency_states = (step_states[dependency_id] for dependency_id in step.depends_on)
            if any(state.status is not ExecutionStepStatus.SUCCEEDED for state in dependency_states):
                step_states[step_id] = ExecutionStepState(
                    step_id=step_id,
                    status=ExecutionStepStatus.BLOCKED,
                    block_reason=ExecutionBlockReason.DEPENDENCY_FAILED,
                )
                continue

            arguments = self._resolve_arguments(step, runtime_outputs)
            if arguments is None:
                step_states[step_id] = ExecutionStepState(
                    step_id=step_id,
                    status=ExecutionStepStatus.BLOCKED,
                    block_reason=ExecutionBlockReason.RUNTIME_OUTPUT_UNAVAILABLE,
                )
                continue

            definition = self._registry.get(step.tool_id)
            # Construct the typed destination input before handing plain values to
            # the existing invoker boundary. The adapter validates again at its
            # external boundary, which keeps V2.5 behavior intact.
            typed_input = definition.validate_arguments(arguments)
            step_states[step_id] = ExecutionStepState(
                step_id=step_id, status=ExecutionStepStatus.RUNNING
            )
            result, attempts, budget_state, retry_budget_exhausted = await self._invoke_with_retries(
                step.tool_id,
                typed_input.model_dump(),
                budget_state,
                resolved_retry_policy,
            )

            if result.outcome is ToolOutcome.FAILED:
                step_states[step_id] = ExecutionStepState(
                    step_id=step_id,
                    status=ExecutionStepStatus.FAILED,
                    attempts=attempts,
                    tool_result=result,
                    failure=result.failure,
                )
                missing_information.append(self._missing_source(step_id, result.failure))
                if retry_budget_exhausted:
                    termination_reason = ExecutionTerminationReason.BUDGET_EXHAUSTED
                    self._block_remaining_steps(
                        step_states,
                        validated_plan.topological_step_ids[position + 1 :],
                    )
                    break
                continue

            merged_evidence = self._merge_evidence(evidence, result.evidence)
            if merged_evidence != evidence:
                evidence = merged_evidence
                # Rules may combine a new observation with an earlier one, so this
                # intentionally replays deterministic derivation over the whole set.
                facts = derive_facts(evidence)
            outputs = self._runtime_outputs(definition.plan_output_model, result)
            runtime_outputs[step_id] = outputs
            step_states[step_id] = ExecutionStepState(
                step_id=step_id,
                status=ExecutionStepStatus.SUCCEEDED,
                attempts=attempts,
                tool_result=result,
            )

        return InvestigationExecutionState(
            validated_plan=validated_plan,
            step_states=tuple(step_states[step_id] for step_id in validated_plan.topological_step_ids),
            runtime_outputs=runtime_outputs,
            evidence=evidence,
            facts=facts,
            missing_information=tuple(missing_information),
            budget=budget_state,
            termination_reason=termination_reason,
        )

    # PURPOSE: Execute one already-validated read-only tool step, accounting for
    # each external call and retrying only failures classified as transient.
    #
    # FLOW: Reserve budget -> invoke -> inspect the typed result -> either return
    # it, stop for exhausted retry budget, or await the next exponential delay.
    #
    # WHY: Reserving here, immediately before every call, ensures an SDK or
    # adapter cannot make a retry that V2.10 failed to count.
    async def _invoke_with_retries(
        self,
        tool_id,
        arguments: Mapping[str, object],
        budget_state: BudgetState,
        retry_policy: RetryPolicy,
    ) -> tuple[ToolResult, int, BudgetState, bool]:
        attempts = 0
        while True:
            # Reserve before every call, including retries. A provider result is
            # never allowed to make an unaccounted-for external attempt.
            budget_state = budget_state.consume_attempt()
            attempts += 1
            result = await self._invoker.invoke(tool_id, arguments)
            failure = result.failure
            can_retry = (
                result.outcome is ToolOutcome.FAILED
                and failure is not None
                and failure.retryable
                and attempts < retry_policy.max_attempts
            )
            if not can_retry:
                return result, attempts, budget_state, False
            if budget_state.remaining_tool_calls == 0:
                return result, attempts, budget_state, True
            await self._sleep(retry_policy.delay_after_failure(attempts))

    @staticmethod
    def _block_remaining_steps(
        step_states: dict[str, ExecutionStepState],
        remaining_step_ids: tuple[str, ...],
    ) -> None:
        for remaining_step_id in remaining_step_ids:
            step_states[remaining_step_id] = ExecutionStepState(
                step_id=remaining_step_id,
                status=ExecutionStepStatus.BLOCKED,
                block_reason=ExecutionBlockReason.BUDGET_EXHAUSTED,
            )

    @staticmethod
    def _resolve_arguments(
        step: PlanStep,
        runtime_outputs: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any] | None:
        resolved_arguments: dict[str, Any] = {}
        for argument in step.arguments:
            if isinstance(argument.value, Literal):
                resolved_arguments[argument.name] = argument.value.value
                continue
            reference = argument.value
            assert isinstance(reference, StepOutputRef)
            source_outputs = runtime_outputs.get(reference.step_id)
            if source_outputs is None or reference.field not in source_outputs:
                return None
            resolved_arguments[argument.name] = source_outputs[reference.field]
        return resolved_arguments

    @staticmethod
    def _runtime_outputs(output_model: type[ContractModel], result: ToolResult) -> dict[str, Any]:
        # Static contracts approve field *names*; this projection supplies concrete
        # values only from normalized Evidence, never from provider-specific payloads.
        if result.outcome is not ToolOutcome.OBSERVED:
            return {}
        output_values: dict[str, Any] = {}
        for field_name in output_model.model_fields:
            values = {
                getattr(evidence.content, field_name)
                for evidence in result.evidence
                if hasattr(evidence.content, field_name)
            }
            if len(values) == 1:
                output_values[field_name] = values.pop()
        return output_values

    @staticmethod
    def _deduplicate_evidence(evidence: tuple[Evidence, ...]) -> tuple[Evidence, ...]:
        return AgentExecutor._merge_evidence((), evidence)

    @staticmethod
    def _merge_evidence(
        accumulated: tuple[Evidence, ...],
        incoming: tuple[Evidence, ...],
    ) -> tuple[Evidence, ...]:
        evidence_by_id = {item.evidence_id: item for item in accumulated}
        for item in incoming:
            evidence_by_id.setdefault(item.evidence_id, item)
        return tuple(evidence_by_id.values())

    @staticmethod
    def _missing_source(step_id: str, failure: ToolFailure | None) -> MissingInformation:
        failure_code = failure.code.value if failure is not None else "source_failure"
        return MissingInformation(
            missing_information_id=f"missing:{step_id}:{failure_code}",
            kind=MissingInformationKind.SOURCE_DATA_UNAVAILABLE,
            detail="A planned tool call did not return usable evidence.",
        )
