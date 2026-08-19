from enum import StrEnum
from typing import Annotated, Literal as TypingLiteral, Self

from pydantic import Field, StringConstraints, model_validator

from app.connectors.models import ContractModel, NonEmptyString
from app.investigations.models import (
    EvidenceKind,
    EvidenceSource,
    FactSet,
    InvestigationIdentifier,
    MissingInformation,
)
from app.tools.models import InvestigationToolId, ToolOutcome


PlanStepIdentifier = Annotated[
    str,
    StringConstraints(pattern=r"^s[1-9][0-9]*$", min_length=2, max_length=32),
]
PlanFieldName = Annotated[
    str,
    StringConstraints(
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", min_length=1, max_length=128
    ),
]
PlanToolIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[a-z][a-z0-9_]*$",
        min_length=1,
        max_length=128,
    ),
]
PlanReason = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
]
LiteralValue = str | int | float | bool | None
MAX_PLAN_STEPS = 5
# Adaptive execution uses a narrower horizon without changing the established
# V2.7/V2.8 contract for callers that still validate a five-step plan.
MAX_ADAPTIVE_PLAN_STEPS = 3


class PlannerToolInputField(ContractModel):
    name: PlanFieldName
    required: bool


class PlannerToolDefinition(ContractModel):
    tool_id: InvestigationToolId
    description: NonEmptyString
    input_fields: tuple[PlannerToolInputField, ...] = ()


class CompactEvidenceContext(ContractModel):
    evidence_id: InvestigationIdentifier
    source: EvidenceSource
    kind: EvidenceKind
    source_reference: NonEmptyString
    summary: NonEmptyString


class ActionSummary(ContractModel):
    """Safe, compact record of one completed logical action for replanning."""

    tool_id: InvestigationToolId
    outcome: ToolOutcome
    produced_new_evidence: bool
    produced_new_facts: bool


class PlannerInput(ContractModel):
    # PURPOSE: Bound what untrusted model reasoning can see to the state needed
    # for choosing evidence work; it is not an InvestigationResult replacement.
    investigation_goal: NonEmptyString
    facts: FactSet = ()
    missing_information: tuple[MissingInformation, ...] = ()
    evidence: tuple[CompactEvidenceContext, ...] = ()
    action_history: tuple[ActionSummary, ...] = ()
    remaining_tool_calls: int = Field(default=0, ge=0)
    planning_round: int = Field(default=1, ge=1)
    max_planning_rounds: int = Field(default=1, ge=1)
    allowed_tools: tuple[PlannerToolDefinition, ...] = Field(min_length=1)


class Literal(ContractModel):
    value_kind: TypingLiteral["literal"] = "literal"
    value: LiteralValue


class StepOutputRef(ContractModel):
    value_kind: TypingLiteral["step_output_ref"] = "step_output_ref"
    step_id: PlanStepIdentifier
    field: PlanFieldName


PlanArgumentValue = Annotated[
    Literal | StepOutputRef,
    Field(discriminator="value_kind"),
]


class PlanArgument(ContractModel):
    name: PlanFieldName
    value: PlanArgumentValue


class PlanStep(ContractModel):
    step_id: PlanStepIdentifier
    tool_id: PlanToolIdentifier
    arguments: tuple[PlanArgument, ...] = Field(default=(), max_length=20)
    depends_on: tuple[PlanStepIdentifier, ...] = Field(default=(), max_length=5)
    reason: PlanReason

    @model_validator(mode="after")
    def validate_unique_local_fields(self) -> Self:
        argument_names = tuple(argument.name for argument in self.arguments)
        if len(argument_names) != len(set(argument_names)):
            raise ValueError("plan step arguments cannot repeat names")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("plan step dependencies cannot repeat identifiers")
        return self


class InvestigationPlan(ContractModel):
    # PURPOSE: Represent a schema-valid proposal. V2.8 owns semantic checks such
    # as duplicate identities and graph legality; V2.9 will decide execution.
    steps: tuple[PlanStep, ...] = Field(min_length=1, max_length=MAX_PLAN_STEPS)


class PlannerFailureCode(StrEnum):
    PROVIDER_FAILURE = "provider_failure"
    INVALID_RESPONSE = "invalid_response"
    PLAN_SCHEMA_INVALID = "plan_schema_invalid"


class PlannerMetadata(ContractModel):
    provider: NonEmptyString
    model: NonEmptyString
    prompt_id: NonEmptyString
    prompt_version: NonEmptyString


class PlannedInvestigation(ContractModel):
    # Metadata belongs beside the proposal so audits can identify the model and
    # prompt without making either one part of the authoritative plan itself.
    plan: InvestigationPlan
    metadata: PlannerMetadata
