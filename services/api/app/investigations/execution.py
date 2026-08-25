import asyncio
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from enum import StrEnum
from typing import Any, Awaitable, Callable
from uuid import UUID

from pydantic import Field

from app.connectors.models import ContractModel, NonEmptyString
from app.investigations import FactSet, MissingInformation, MissingInformationKind
from app.investigations.baseline import ToolInvoker
from app.investigations.evidence_store import EvidenceStore
from app.investigations.fact_derivation import derive_facts
from app.investigations.models import InvestigationIdentifier
from app.investigations.planning import Literal, PlanStep, StepOutputRef, ValidatedPlan
from app.investigations.planning.models import PlanStepIdentifier
from app.observability.contracts import (
    FailureCategory,
    InvestigationStage,
    InvestigationStageResult,
)
from app.observability.runtime_telemetry import RuntimeTelemetry
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


class RetryPolicy(ContractModel):
    max_attempts: int = Field(default=3, ge=1, le=3)
    initial_backoff_seconds: float = Field(default=1.0, gt=0, le=60)
    backoff_multiplier: float = Field(default=2.0, ge=2, le=2)

    def delay_after_failure(self, completed_attempts: int) -> float:
        return self.initial_backoff_seconds * (
            self.backoff_multiplier ** (completed_attempts - 1)
        )


class BudgetState(ContractModel):
    max_tool_calls: int = Field(ge=0, le=100)
    used_tool_calls: int = Field(default=0, ge=0)

    @property
    def remaining_tool_calls(self) -> int:
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
    validated_plan: ValidatedPlan
    step_states: tuple[ExecutionStepState, ...]
    runtime_outputs: dict[PlanStepIdentifier, dict[str, Any]] = Field(default_factory=dict)
    evidence: tuple[InvestigationIdentifier, ...] = ()
    facts: FactSet = ()
    missing_information: tuple[MissingInformation, ...] = ()
    budget: BudgetState
    termination_reason: ExecutionTerminationReason


class AgentExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        invoker: ToolInvoker,
        store: EvidenceStore,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        telemetry: RuntimeTelemetry | None = None,
        run_id: UUID | None = None,
    ) -> None:
        self._registry = registry
        self._invoker = invoker
        self._store = store
        self._sleep = sleep
        self._telemetry = telemetry
        self._run_id = run_id

    async def execute(
        self,
        validated_plan: ValidatedPlan,
        *,
        budget: ExecutionBudget,
        initial_evidence: tuple[InvestigationIdentifier, ...] = (),
        retry_policy: RetryPolicy | None = None,
        round_number: int | None = None,
    ) -> InvestigationExecutionState:
        evidence = self._deduplicate_evidence(initial_evidence)
        with self._observe_stage(
            InvestigationStage.FACT_DERIVATION,
            round_number=round_number,
        ):
            facts = derive_facts(self._store.get_many(evidence))
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


            typed_input = definition.validate_arguments(arguments)
            step_states[step_id] = ExecutionStepState(
                step_id=step_id, status=ExecutionStepStatus.RUNNING
            )
            (
                result,
                attempts,
                budget_state,
                retry_budget_exhausted,
            ) = await self._invoke_with_retries(
                step.tool_id,
                typed_input.model_dump(),
                budget_state,
                resolved_retry_policy,
                round_number,
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

            merged_evidence = self._merge_evidence(evidence, result.evidence_ids)
            if merged_evidence != evidence:
                evidence = merged_evidence


                with self._observe_stage(
                    InvestigationStage.FACT_DERIVATION,
                    round_number=round_number,
                ):
                    facts = derive_facts(self._store.get_many(evidence))
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


    async def _invoke_with_retries(
        self,
        tool_id,
        arguments: Mapping[str, object],
        budget_state: BudgetState,
        retry_policy: RetryPolicy,
        round_number: int | None,
    ) -> tuple[ToolResult, int, BudgetState, bool]:
        attempts = 0
        while True:
            budget_state = budget_state.consume_attempt()
            attempts += 1


            with self._observe_stage(
                InvestigationStage.TOOL_EXECUTION,
                round_number=round_number,
                tool_id=str(tool_id),
                attempt=attempts,
            ) as observation:
                result = await self._invoker.invoke(tool_id, arguments)
                if observation is not None:
                    observation.set_attributes(
                        **{"promptql.connector.result": result.outcome.value}
                    )
                    if result.outcome is ToolOutcome.FAILED:
                        observation.set_stage_result(
                            InvestigationStageResult.FAILED
                        )
                        observation.mark_error(FailureCategory.CONNECTOR_FAILURE)
            if self._telemetry is not None:
                self._telemetry.record_investigation_tool_call(
                    str(tool_id),
                    result.outcome.value,
                )
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
            with self._observe_stage(
                InvestigationStage.RETRY,
                round_number=round_number,
                tool_id=str(tool_id),
                attempt=attempts + 1,
            ):
                await self._sleep(retry_policy.delay_after_failure(attempts))

    @contextmanager
    def _observe_stage(
        self,
        stage: InvestigationStage,
        *,
        round_number: int | None = None,
        tool_id: str | None = None,
        attempt: int | None = None,
    ) -> Iterator[object | None]:
        if self._telemetry is None or self._run_id is None:
            yield None
            return
        with self._telemetry.observe_investigation_stage(
            stage,
            self._run_id,
            round_number=round_number,
            tool_id=tool_id,
            attempt=attempt,
        ) as observation:
            yield observation

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

    def _runtime_outputs(self, output_model: type[ContractModel], result: ToolResult) -> dict[str, Any]:
        if result.outcome is not ToolOutcome.OBSERVED:
            return {}
        observed_evidence = self._store.get_many(result.evidence_ids)
        output_values: dict[str, Any] = {}
        for field_name in output_model.model_fields:
            values = {
                getattr(evidence.content, field_name)
                for evidence in observed_evidence
                if hasattr(evidence.content, field_name)
            }
            if len(values) == 1:
                output_values[field_name] = values.pop()
        return output_values

    @staticmethod
    def _deduplicate_evidence(
        evidence: tuple[InvestigationIdentifier, ...],
    ) -> tuple[InvestigationIdentifier, ...]:
        return AgentExecutor._merge_evidence((), evidence)


    @staticmethod
    def _merge_evidence(
        accumulated: tuple[InvestigationIdentifier, ...],
        incoming: tuple[InvestigationIdentifier, ...],
    ) -> tuple[InvestigationIdentifier, ...]:
        ids = list(accumulated)
        seen = set(accumulated)
        for evidence_id in incoming:
            if evidence_id not in seen:
                seen.add(evidence_id)
                ids.append(evidence_id)
        return tuple(ids)

    @staticmethod
    def _missing_source(step_id: str, failure: ToolFailure | None) -> MissingInformation:
        failure_code = failure.code.value if failure is not None else "source_failure"
        return MissingInformation(
            missing_information_id=f"missing:{step_id}:{failure_code}",
            kind=MissingInformationKind.SOURCE_DATA_UNAVAILABLE,
            detail="A planned tool call did not return usable evidence.",
        )
