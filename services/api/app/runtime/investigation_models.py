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
    evidence: tuple[InvestigationIdentifier, ...] = ()
    evidence_content: tuple[Evidence, ...] = ()
    facts: FactSet = ()
    missing_information: tuple[MissingInformation, ...] = ()
    validated_hypotheses: tuple[ValidatedHypothesis, ...] = ()
    validated_code_findings: tuple[ValidatedCodeFinding, ...] = ()
    developer_recommendations: tuple[DeveloperRecommendation, ...] = ()
    action_history: tuple[ActionSummary, ...] = ()


class ExecutionState(ContractModel):
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


MAX_FOLLOW_UPS_PER_CASE = 3


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
    results: tuple[GroundedInvestigationResult, ...] = ()


    follow_up_count: Annotated[int, Field(ge=0)] = 0


    recorded_fact_types: tuple[NonEmptyString, ...] = ()

    @model_validator(mode="after")
    def validate_lifecycle_fields(self) -> Self:
        if self.status is RunStatus.PENDING:
            if self.started_at is not None or self.completed_at is not None:
                raise ValueError("a pending investigation cannot have timestamps")
            if self.error is not None or self.state is not None or self.results:
                raise ValueError("a pending investigation cannot have execution state")
            if self.follow_up_count != 0:
                raise ValueError("a pending investigation cannot have follow-ups yet")
        elif self.status is RunStatus.RUNNING:
            if self.started_at is None or self.completed_at is not None:
                raise ValueError("a running investigation needs only a start timestamp")
            if self.error is not None:
                raise ValueError("a running investigation cannot have terminal output")
        elif self.status is RunStatus.COMPLETED:
            if self.started_at is None or self.completed_at is None:
                raise ValueError("a completed investigation needs timestamps")
            if self.error is not None or self.state is None or not self.results:
                raise ValueError("a completed investigation needs state and at least one result")
        elif self.status in {RunStatus.FAILED, RunStatus.CANCELLED}:
            if self.started_at is None or self.completed_at is None:
                raise ValueError("a terminal investigation needs timestamps")


        return self
