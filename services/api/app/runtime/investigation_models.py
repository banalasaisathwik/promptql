"""Runtime snapshots for the V2 investigation console."""

from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.connectors.models import ContractModel, NonEmptyString
from app.investigations.hypotheses import (
    GroundedInvestigationResult,
    ValidatedHypothesis,
)
from app.investigations.models import (
    Evidence,
    FactSet,
    InvestigationRequest,
    MissingInformation,
)
from app.investigations.execution import (
    ExecutionBlockReason,
    ExecutionStepStatus,
)
from app.investigations.hypotheses.models import RejectedHypothesis
from app.runtime.models import RunStatus, RuntimeErrorInfo


class InvestigationStepSnapshot(ContractModel):
    step_id: NonEmptyString
    tool_id: NonEmptyString
    status: ExecutionStepStatus
    attempts: Annotated[int, Field(ge=0)]
    failure_code: NonEmptyString | None = None
    failure_message: NonEmptyString | None = None
    block_reason: ExecutionBlockReason | None = None


class InvestigationPlanningRoundSnapshot(ContractModel):
    round_number: Annotated[int, Field(ge=1)]
    plan_id: NonEmptyString
    plan_validation_status: NonEmptyString
    steps: tuple[InvestigationStepSnapshot, ...] = ()
    evidence_delta_ids: tuple[NonEmptyString, ...] = ()
    fact_delta_ids: tuple[NonEmptyString, ...] = ()
    completed: bool = False


class InvestigationRuntimeSnapshot(ContractModel):
    # PURPOSE: Store the current investigation projection that a browser needs
    # while execution is in progress or after it terminates.
    #
    # FLOW: The workflow writes rounds and tool states first, then adds normalized
    # Evidence and derived Facts, and finally records validated hypotheses,
    # budget accounting, and the termination reason.
    #
    # WHY: A typed snapshot is sufficient for the existing polling workload and
    # avoids making the UI reconstruct domain state from low-level events.
    rounds: tuple[InvestigationPlanningRoundSnapshot, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    facts: FactSet = ()
    missing_information: tuple[MissingInformation, ...] = ()
    validated_hypotheses: tuple[ValidatedHypothesis, ...] = ()
    rejected_hypothesis_count: Annotated[int, Field(ge=0)] = 0
    max_tool_calls: Annotated[int, Field(ge=0)]
    used_tool_calls: Annotated[int, Field(ge=0)]
    remaining_tool_calls: Annotated[int, Field(ge=0)]
    termination_reason: NonEmptyString | None = None


class InvestigationRun(ContractModel):
    """A durable run variant carried by the same polling endpoint as V1 runs."""

    run_id: UUID
    workflow_name: NonEmptyString
    workflow_version: NonEmptyString
    status: RunStatus
    started_at: datetime | None
    completed_at: datetime | None
    steps: tuple[object, ...] = ()
    error: RuntimeErrorInfo | None
    request: InvestigationRequest
    state: InvestigationRuntimeSnapshot | None
    result: GroundedInvestigationResult | None

    @model_validator(mode="after")
    def validate_lifecycle_fields(self) -> Self:
        # `model_validator(mode="after")` runs after Pydantic has converted the
        # incoming JSON into typed fields, so this is a lifecycle invariant check
        # rather than a frontend-only TypeScript assertion.
        if self.status is RunStatus.PENDING:
            if self.started_at is not None or self.completed_at is not None:
                raise ValueError("a pending investigation cannot have timestamps")
            if self.error is not None or self.state is not None or self.result is not None:
                raise ValueError("a pending investigation cannot have execution state")
        elif self.status is RunStatus.RUNNING:
            if self.started_at is None or self.completed_at is not None:
                raise ValueError("a running investigation needs only a start timestamp")
            if self.error is not None or self.result is not None:
                raise ValueError("a running investigation cannot have terminal output")
        elif self.status is RunStatus.COMPLETED:
            if self.started_at is None or self.completed_at is None:
                raise ValueError("a completed investigation needs timestamps")
            if self.error is not None or self.state is None or self.result is None:
                raise ValueError("a completed investigation needs state and result")
        elif self.status in {RunStatus.FAILED, RunStatus.CANCELLED}:
            if self.started_at is None or self.completed_at is None:
                raise ValueError("a terminal investigation needs timestamps")
            if self.result is not None:
                raise ValueError("a failed investigation cannot have a result")
        return self
