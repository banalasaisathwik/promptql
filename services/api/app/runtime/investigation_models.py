from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.connectors.models import ContractModel, NonEmptyString
from app.investigations.code_diagnosis import (
    CodeDiagnosisMetadata,
    DeveloperRecommendation,
    ValidatedCodeFinding,
)
from app.investigations.hypotheses import (
    GroundedInvestigationResult,
    ValidatedHypothesis,
)
from app.investigations.models import (
    Evidence,
    FactSet,
    InvestigationIdentifier,
    InvestigationRequest,
    MissingInformation,
)
from app.investigations.execution import (
    ExecutionBlockReason,
    ExecutionStepStatus,
)
from app.investigations.hypotheses.models import HypothesisGenerationMetadata
from app.investigations.planning import ActionSummary, PlannerMetadata
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


    planner_metadata: PlannerMetadata | None = None
    steps: tuple[InvestigationStepSnapshot, ...] = ()
    evidence_delta_ids: tuple[NonEmptyString, ...] = ()
    fact_delta_ids: tuple[NonEmptyString, ...] = ()
    completed: bool = False


class WorkingMemory(ContractModel):
    """Semantic investigation knowledge: what the investigation has learned."""

    evidence: tuple[InvestigationIdentifier, ...] = ()
    evidence_content: tuple[Evidence, ...] = ()
    facts: FactSet = ()
    missing_information: tuple[MissingInformation, ...] = ()
    validated_hypotheses: tuple[ValidatedHypothesis, ...] = ()
    validated_code_findings: tuple[ValidatedCodeFinding, ...] = ()
    developer_recommendations: tuple[DeveloperRecommendation, ...] = ()
    action_history: tuple[ActionSummary, ...] = ()


class ExecutionState(ContractModel):
    """Pure execution bookkeeping: how the run has progressed."""

    rounds: tuple[InvestigationPlanningRoundSnapshot, ...] = ()
    hypothesis_generation_metadata: HypothesisGenerationMetadata | None = None
    rejected_hypothesis_count: Annotated[int, Field(ge=0)] = 0
    code_diagnosis_metadata: CodeDiagnosisMetadata | None = None
    rejected_code_finding_count: Annotated[int, Field(ge=0)] = 0
    max_tool_calls: Annotated[int, Field(ge=0)]
    used_tool_calls: Annotated[int, Field(ge=0)]
    remaining_tool_calls: Annotated[int, Field(ge=0)]
    termination_reason: NonEmptyString | None = None


class InvestigationRuntimeSnapshot(ContractModel):
    working_memory: WorkingMemory
    execution_state: ExecutionState


class InvestigationRun(ContractModel):
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
