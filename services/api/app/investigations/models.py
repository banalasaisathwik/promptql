from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.connectors.models import (
    CommitSha,
    ContractModel,
    JiraIssueKey,
    JiraIssueStatus,
    NonEmptyString,
    PullRequestState,
    TelemetryFilter,
    TelemetrySignal,
    TelemetryWindowEvidenceRequest,
)


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
    incident_reference: NonEmptyString | None = None
    deployment_reference: NonEmptyString | None = None
    pull_request_number: Annotated[int, Field(strict=True, gt=0)] | None = None
    jira_issue_key: JiraIssueKey | None = None
    telemetry_window: TelemetryWindowEvidenceRequest | None = None
    incident_started_at: datetime | None = None
    service: NonEmptyString | None = None
    environment: NonEmptyString | None = None


class FileChangeType(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


EvidenceSourceReference = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]
EvidenceText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4096),
]
EvidenceFilePath = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4096),
]
DiffLineText = Annotated[str, StringConstraints(max_length=4096)]


class EvidenceSource(StrEnum):
    GITHUB = "github"
    JIRA = "jira"
    INCIDENT = "incident"
    DEPLOYMENT = "deployment"
    TELEMETRY = "telemetry"


class EvidenceKind(StrEnum):
    CHANGED_FILE = "changed_file"
    COMMIT = "commit"
    PULL_REQUEST = "pull_request"
    DIFF_HUNK = "diff_hunk"
    JIRA_ISSUE = "jira_issue"
    STACK_FRAME = "stack_frame"
    DEPLOYMENT = "deployment"
    INCIDENT = "incident"
    TELEMETRY_WINDOW = "telemetry_window"


class EvidenceProvenance(ContractModel):
    source_reference: EvidenceSourceReference
    observed_at: AwareDatetime | None = None
    retrieved_at: AwareDatetime


class ChangedFileEvidenceContent(ContractModel):
    content_type: Literal["changed_file"] = "changed_file"
    repository_owner: NonEmptyString
    repository_name: NonEmptyString
    pull_request_number: Annotated[int, Field(strict=True, gt=0)]
    path: EvidenceFilePath
    change_type: FileChangeType
    previous_path: NonEmptyString | None = None
    additions: Annotated[int, Field(strict=True, ge=0)]
    deletions: Annotated[int, Field(strict=True, ge=0)]
    changes: Annotated[int, Field(strict=True, ge=0)]
    patch_available: bool

    @model_validator(mode="after")
    def validate_change_metadata(self) -> Self:
        if self.changes != self.additions + self.deletions:
            raise ValueError("file changes must equal additions plus deletions")
        if self.change_type is FileChangeType.RENAMED:
            if self.previous_path is None or self.previous_path == self.path:
                raise ValueError("a renamed file needs a distinct previous path")
        elif self.previous_path is not None:
            raise ValueError("only renamed files may carry a previous path")
        return self


class CommitEvidenceContent(ContractModel):
    content_type: Literal["commit"] = "commit"
    repository_owner: NonEmptyString
    repository_name: NonEmptyString
    commit_sha: CommitSha
    message: EvidenceText
    authored_at: AwareDatetime | None = None
    parent_shas: Annotated[tuple[CommitSha, ...], Field(max_length=100)] = ()

    @model_validator(mode="after")
    def validate_parents(self) -> Self:
        if len(self.parent_shas) != len(set(self.parent_shas)):
            raise ValueError("commit parents must be unique")
        if self.commit_sha in self.parent_shas:
            raise ValueError("a commit cannot be its own parent")
        return self


class PullRequestEvidenceContent(ContractModel):
    content_type: Literal["pull_request"] = "pull_request"
    repository_owner: NonEmptyString
    repository_name: NonEmptyString
    pull_request_number: Annotated[int, Field(strict=True, gt=0)]
    title: EvidenceText
    state: PullRequestState
    base_sha: CommitSha
    head_sha: CommitSha
    merge_commit_sha: CommitSha | None = None


class DiffLineKind(StrEnum):
    CONTEXT = "context"
    ADDITION = "addition"
    DELETION = "deletion"


class DiffLine(ContractModel):
    kind: DiffLineKind
    text: DiffLineText


class DiffHunkEvidenceContent(ContractModel):
    content_type: Literal["diff_hunk"] = "diff_hunk"
    repository_owner: NonEmptyString
    repository_name: NonEmptyString
    pull_request_number: Annotated[int, Field(strict=True, gt=0)]
    file_path: EvidenceFilePath
    old_start: Annotated[int, Field(strict=True, ge=0)]
    old_count: Annotated[int, Field(strict=True, ge=0)]
    new_start: Annotated[int, Field(strict=True, ge=0)]
    new_count: Annotated[int, Field(strict=True, ge=0)]
    lines: Annotated[tuple[DiffLine, ...], Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def validate_line_ranges(self) -> Self:
        old_line_count = sum(
            line.kind in {DiffLineKind.CONTEXT, DiffLineKind.DELETION}
            for line in self.lines
        )
        new_line_count = sum(
            line.kind in {DiffLineKind.CONTEXT, DiffLineKind.ADDITION}
            for line in self.lines
        )
        if old_line_count != self.old_count or new_line_count != self.new_count:
            raise ValueError("diff lines must agree with the declared old/new ranges")
        return self


class JiraIssueEvidenceContent(ContractModel):
    content_type: Literal["jira_issue"] = "jira_issue"
    issue_key: JiraIssueKey
    status: JiraIssueStatus


class IncidentStatus(StrEnum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    UNKNOWN = "unknown"


class IncidentEvidenceContent(ContractModel):
    content_type: Literal["incident"] = "incident"
    incident_reference: NonEmptyString
    service: NonEmptyString | None = None
    environment: NonEmptyString | None = None
    started_at: AwareDatetime | None = None
    status: IncidentStatus | None = None
    category: NonEmptyString | None = None


class StackFrameEvidenceContent(ContractModel):
    content_type: Literal["stack_frame"] = "stack_frame"
    service: NonEmptyString | None = None
    error_category: NonEmptyString | None = None
    file_path: NonEmptyString | None = None
    function_name: NonEmptyString | None = None
    line_number: Annotated[int, Field(strict=True, gt=0)] | None = None

    @model_validator(mode="after")
    def validate_failure_location(self) -> Self:
        if self.error_category is None and self.file_path is None:
            raise ValueError("a stack frame needs an error category or file path")
        if self.line_number is not None and self.file_path is None:
            raise ValueError("a stack-frame line number requires a file path")
        return self


class DeploymentEvidenceContent(ContractModel):
    content_type: Literal["deployment"] = "deployment"
    deployment_reference: NonEmptyString
    service: NonEmptyString
    environment: NonEmptyString
    commit_sha: CommitSha
    deployed_at: AwareDatetime


class TelemetryWindowEvidenceContent(ContractModel):
    content_type: Literal["telemetry_window"] = "telemetry_window"
    service: NonEmptyString
    signal: TelemetrySignal
    start_time: AwareDatetime
    end_time: AwareDatetime
    filters: Annotated[tuple[TelemetryFilter, ...], Field(max_length=20)] = ()
    event_count: Annotated[int, Field(strict=True, ge=0)]

    @model_validator(mode="after")
    def validate_window_and_filters(self) -> Self:
        if self.start_time >= self.end_time:
            raise ValueError("telemetry start_time must be before end_time")
        filter_pairs = {(filter.key, filter.value) for filter in self.filters}
        if len(filter_pairs) != len(self.filters):
            raise ValueError("telemetry filters cannot contain duplicate key/value pairs")
        return self


EvidenceContent = Annotated[
    ChangedFileEvidenceContent
    | CommitEvidenceContent
    | PullRequestEvidenceContent
    | DiffHunkEvidenceContent
    | JiraIssueEvidenceContent
    | IncidentEvidenceContent
    | StackFrameEvidenceContent
    | DeploymentEvidenceContent
    | TelemetryWindowEvidenceContent,
    Field(discriminator="content_type"),
]


_EXPECTED_SOURCE_BY_KIND = {
    EvidenceKind.CHANGED_FILE: EvidenceSource.GITHUB,
    EvidenceKind.COMMIT: EvidenceSource.GITHUB,
    EvidenceKind.PULL_REQUEST: EvidenceSource.GITHUB,
    EvidenceKind.DIFF_HUNK: EvidenceSource.GITHUB,
    EvidenceKind.JIRA_ISSUE: EvidenceSource.JIRA,
    EvidenceKind.INCIDENT: EvidenceSource.INCIDENT,
    EvidenceKind.STACK_FRAME: EvidenceSource.INCIDENT,
    EvidenceKind.DEPLOYMENT: EvidenceSource.DEPLOYMENT,
    EvidenceKind.TELEMETRY_WINDOW: EvidenceSource.TELEMETRY,
}


class Evidence(ContractModel):
    evidence_id: InvestigationIdentifier
    source: EvidenceSource
    kind: EvidenceKind
    provenance: EvidenceProvenance
    content: EvidenceContent

    @model_validator(mode="after")
    def validate_source_and_content(self) -> Self:
        if self.kind.value != self.content.content_type:
            raise ValueError("evidence kind must match its content type")
        if _EXPECTED_SOURCE_BY_KIND[self.kind] is not self.source:
            raise ValueError("evidence source is incompatible with its kind")
        return self


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


class DeploymentPrecededIncidentFact(_EvidenceBackedFact):
    fact_type: Literal["deployment_preceded_incident"] = "deployment_preceded_incident"
    deployment_reference: NonEmptyString
    incident_reference: NonEmptyString


class DeploymentReferencesCommitFact(_EvidenceBackedFact):
    fact_type: Literal["deployment_references_commit"] = "deployment_references_commit"
    deployment_reference: NonEmptyString
    commit_sha: CommitSha


class CommitAssociatedWithPullRequestFact(_EvidenceBackedFact):
    fact_type: Literal["commit_associated_with_pull_request"] = "commit_associated_with_pull_request"
    commit_sha: CommitSha
    pull_request_number: Annotated[int, Field(strict=True, gt=0)]


class ChangedFileMatchesFailureFileFact(_EvidenceBackedFact):
    fact_type: Literal["changed_file_matches_failure_file"] = "changed_file_matches_failure_file"
    file_path: NonEmptyString


class ChangedHunkOverlapsFailureLineFact(_EvidenceBackedFact):
    fact_type: Literal["changed_hunk_overlaps_failure_line"] = "changed_hunk_overlaps_failure_line"
    file_path: NonEmptyString
    line_number: Annotated[int, Field(strict=True, gt=0)]


InvestigationFact = Annotated[
    ChangedFileFact
    | DeploymentFact
    | StackFrameFact
    | DeploymentPrecededIncidentFact
    | DeploymentReferencesCommitFact
    | CommitAssociatedWithPullRequestFact
    | ChangedFileMatchesFailureFileFact
    | ChangedHunkOverlapsFailureLineFact,
    Field(discriminator="fact_type"),
]
FactSet = tuple[InvestigationFact, ...]


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
    evidence: tuple[Evidence, ...]
    facts: tuple[InvestigationFact, ...]
    hypotheses: tuple[Hypothesis, ...]
    missing_information: tuple[MissingInformation, ...]
    recommended_actions: tuple[RecommendedAction, ...]

    @model_validator(mode="after")
    def validate_identity_and_references(self) -> Self:
        evidence_ids = {evidence.evidence_id for evidence in self.evidence}
        fact_ids = {fact.fact_id for fact in self.facts}
        hypothesis_ids = {
            hypothesis.hypothesis_id for hypothesis in self.hypotheses
        }
        missing_information_ids = {
            item.missing_information_id for item in self.missing_information
        }
        action_ids = {action.action_id for action in self.recommended_actions}

        entity_ids = [
            *(evidence.evidence_id for evidence in self.evidence),
            *(fact.fact_id for fact in self.facts),
            *(hypothesis.hypothesis_id for hypothesis in self.hypotheses),
            *(item.missing_information_id for item in self.missing_information),
            *(action.action_id for action in self.recommended_actions),
        ]
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError("entity identifiers must be unique within a result")

        for fact in self.facts:
            if not set(fact.evidence_reference_ids) <= evidence_ids:
                raise ValueError("fact references unknown evidence")

        for hypothesis in self.hypotheses:
            if not set(hypothesis.related_fact_ids) <= fact_ids:
                raise ValueError("hypothesis references an unknown fact")
            if not set(hypothesis.evidence_reference_ids) <= evidence_ids:
                raise ValueError("hypothesis references unknown evidence")

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
