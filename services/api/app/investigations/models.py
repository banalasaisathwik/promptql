from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from app.connectors.models import ContractModel, NonEmptyString


InvestigationIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
EvidenceReferenceIds = Annotated[
    tuple[InvestigationIdentifier, ...],
    Field(min_length=1),
]


def _validate_unique_references(
    reference_ids: tuple[InvestigationIdentifier, ...],
    relationship_name: str,
) -> None:
    if len(reference_ids) != len(set(reference_ids)):
        raise ValueError(f"{relationship_name} cannot contain duplicate identifiers")


class InvestigationRequest(ContractModel):
    repository_owner: NonEmptyString
    repository_name: NonEmptyString
    incident_summary: NonEmptyString
    incident_started_at: datetime | None = None
    service: NonEmptyString | None = None
    environment: NonEmptyString | None = None


class FileChangeType(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


class _EvidenceBackedFact(ContractModel):
    fact_id: InvestigationIdentifier
    evidence_reference_ids: EvidenceReferenceIds

    @model_validator(mode="after")
    def validate_evidence_references(self) -> Self:
        _validate_unique_references(
            self.evidence_reference_ids,
            "evidence_reference_ids",
        )
        return self


class ChangedFileFact(_EvidenceBackedFact):
    fact_type: Literal["changed_file"] = "changed_file"
    path: NonEmptyString
    change_type: FileChangeType


class DeploymentFact(_EvidenceBackedFact):
    fact_type: Literal["deployment"] = "deployment"
    deployment_reference: NonEmptyString
    environment: NonEmptyString
    deployed_at: datetime
    revision: NonEmptyString


class StackFrameFact(_EvidenceBackedFact):
    fact_type: Literal["stack_frame"] = "stack_frame"
    file_path: NonEmptyString
    function_name: NonEmptyString
    line_number: Annotated[int, Field(strict=True, gt=0)]


InvestigationFact = Annotated[
    ChangedFileFact | DeploymentFact | StackFrameFact,
    Field(discriminator="fact_type"),
]


class HypothesisConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class HypothesisGroundingStatus(StrEnum):
    SUPPORTED = "supported"
    WEAKLY_SUPPORTED = "weakly_supported"
    CONTRADICTED = "contradicted"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class Hypothesis(ContractModel):
    hypothesis_id: InvestigationIdentifier
    code: InvestigationIdentifier
    claim: NonEmptyString
    related_fact_ids: tuple[InvestigationIdentifier, ...] = ()
    evidence_reference_ids: tuple[InvestigationIdentifier, ...] = ()
    confidence: HypothesisConfidence
    grounding_status: HypothesisGroundingStatus

    @model_validator(mode="after")
    def validate_grounding_references(self) -> Self:
        _validate_unique_references(self.related_fact_ids, "related_fact_ids")
        _validate_unique_references(
            self.evidence_reference_ids,
            "evidence_reference_ids",
        )
        grounding_requires_support = self.grounding_status in {
            HypothesisGroundingStatus.SUPPORTED,
            HypothesisGroundingStatus.WEAKLY_SUPPORTED,
            HypothesisGroundingStatus.CONTRADICTED,
        }
        if grounding_requires_support and not (
            self.related_fact_ids or self.evidence_reference_ids
        ):
            raise ValueError(
                "a grounded or contradicted hypothesis must cite a fact or evidence"
            )
        return self


class MissingInformationKind(StrEnum):
    DEPLOYMENT_MAPPING_UNAVAILABLE = "deployment_mapping_unavailable"
    INCIDENT_TIMELINE_INCOMPLETE = "incident_timeline_incomplete"
    SOURCE_DATA_UNAVAILABLE = "source_data_unavailable"


class MissingInformation(ContractModel):
    missing_information_id: InvestigationIdentifier
    kind: MissingInformationKind
    detail: NonEmptyString | None = None
    related_fact_ids: tuple[InvestigationIdentifier, ...] = ()
    related_hypothesis_ids: tuple[InvestigationIdentifier, ...] = ()

    @model_validator(mode="after")
    def validate_relationships(self) -> Self:
        _validate_unique_references(self.related_fact_ids, "related_fact_ids")
        _validate_unique_references(
            self.related_hypothesis_ids,
            "related_hypothesis_ids",
        )
        return self


class RecommendedActionCode(StrEnum):
    COLLECT_DEPLOYMENT_MAPPING = "collect_deployment_mapping"
    COLLECT_INCIDENT_TIMELINE = "collect_incident_timeline"
    RETRIEVE_SOURCE_DATA = "retrieve_source_data"
    VALIDATE_HYPOTHESIS = "validate_hypothesis"


class RecommendedAction(ContractModel):
    action_id: InvestigationIdentifier
    action_code: RecommendedActionCode
    message: NonEmptyString
    related_fact_ids: tuple[InvestigationIdentifier, ...] = ()
    related_missing_information_ids: tuple[InvestigationIdentifier, ...] = ()
    related_hypothesis_ids: tuple[InvestigationIdentifier, ...] = ()

    @model_validator(mode="after")
    def validate_reason_references(self) -> Self:
        _validate_unique_references(self.related_fact_ids, "related_fact_ids")
        _validate_unique_references(
            self.related_missing_information_ids,
            "related_missing_information_ids",
        )
        _validate_unique_references(
            self.related_hypothesis_ids,
            "related_hypothesis_ids",
        )
        if not (
            self.related_fact_ids
            or self.related_missing_information_ids
            or self.related_hypothesis_ids
        ):
            raise ValueError(
                "a recommended action must reference a fact, missing information, or a hypothesis"
            )
        return self


class InvestigationResult(ContractModel):
    facts: tuple[InvestigationFact, ...]
    hypotheses: tuple[Hypothesis, ...]
    missing_information: tuple[MissingInformation, ...]
    recommended_actions: tuple[RecommendedAction, ...]

    @model_validator(mode="after")
    def validate_identity_and_references(self) -> Self:
        fact_ids = {fact.fact_id for fact in self.facts}
        hypothesis_ids = {
            hypothesis.hypothesis_id for hypothesis in self.hypotheses
        }
        missing_information_ids = {
            item.missing_information_id for item in self.missing_information
        }
        action_ids = {action.action_id for action in self.recommended_actions}

        entity_ids = [
            *(fact.fact_id for fact in self.facts),
            *(hypothesis.hypothesis_id for hypothesis in self.hypotheses),
            *(item.missing_information_id for item in self.missing_information),
            *(action.action_id for action in self.recommended_actions),
        ]
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError("entity identifiers must be unique within a result")

        for hypothesis in self.hypotheses:
            if not set(hypothesis.related_fact_ids) <= fact_ids:
                raise ValueError("hypothesis references an unknown fact")

        for item in self.missing_information:
            if not set(item.related_fact_ids) <= fact_ids:
                raise ValueError("missing information references an unknown fact")
            if not set(item.related_hypothesis_ids) <= hypothesis_ids:
                raise ValueError("missing information references an unknown hypothesis")

        for action in self.recommended_actions:
            if not set(action.related_fact_ids) <= fact_ids:
                raise ValueError("recommended action references an unknown fact")
            if not (
                set(action.related_missing_information_ids)
                <= missing_information_ids
            ):
                raise ValueError("recommended action references unknown missing information")
            if not set(action.related_hypothesis_ids) <= hypothesis_ids:
                raise ValueError("recommended action references an unknown hypothesis")

        return self
