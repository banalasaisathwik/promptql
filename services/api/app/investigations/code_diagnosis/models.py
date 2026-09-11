from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from app.connectors.models import ContractModel, NonEmptyString
from app.explanations.models import LLMTokenUsage
from app.investigations.models import (
    DiffLineKind,
    FactSet,
    InvestigationIdentifier,
)


MAX_CODE_FINDINGS = 3
MAX_CODE_CONTEXT_LOCATIONS = 20
MAX_CODE_LINES_PER_HUNK = 20
MAX_PROPOSED_FIX_LINES = 60
MAX_PROPOSED_FIX_EXPANSION_LINES = 20
CodeExplanation = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
CodeLineText = Annotated[str, StringConstraints(max_length=300)]


class CodeContextKind(StrEnum):
    CHANGED_FILE = "changed_file"
    DIFF_HUNK = "diff_hunk"
    STACK_FRAME = "stack_frame"


class CodeContextLine(ContractModel):
    kind: DiffLineKind
    text: CodeLineText


class CodeContextLocation(ContractModel):
    evidence_id: InvestigationIdentifier
    kind: CodeContextKind
    file_path: NonEmptyString
    line_start: Annotated[int, Field(strict=True, gt=0)] | None = None
    line_end: Annotated[int, Field(strict=True, gt=0)] | None = None
    function_name: NonEmptyString | None = None
    error_category: NonEmptyString | None = None
    lines: Annotated[
        tuple[CodeContextLine, ...],
        Field(max_length=MAX_CODE_LINES_PER_HUNK),
    ] = ()

    @model_validator(mode="after")
    def validate_location_shape(self) -> Self:
        if (self.line_start is None) != (self.line_end is None):
            raise ValueError("code context line bounds must be supplied together")
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_start > self.line_end
        ):
            raise ValueError("code context line bounds must be ordered")
        if self.kind is not CodeContextKind.DIFF_HUNK and self.lines:
            raise ValueError("only diff-hunk context may contain code lines")
        if self.kind is CodeContextKind.CHANGED_FILE and any(
            value is not None
            for value in (
                self.line_start,
                self.function_name,
                self.error_category,
            )
        ):
            raise ValueError("changed-file context cannot invent a code location")
        if self.kind is CodeContextKind.DIFF_HUNK and (
            self.function_name is not None or self.error_category is not None
        ):
            raise ValueError("diff-hunk context cannot carry stack-frame metadata")
        if (
            self.kind is CodeContextKind.STACK_FRAME
            and self.line_start != self.line_end
        ):
            raise ValueError("stack-frame context represents at most one line")
        return self


class CodeDiagnosisSupport(ContractModel):
    hypothesis_id: InvestigationIdentifier
    file_path: NonEmptyString
    supporting_fact_ids: Annotated[
        tuple[InvestigationIdentifier, ...],
        Field(min_length=1, max_length=10),
    ]
    supporting_evidence_ids: Annotated[
        tuple[InvestigationIdentifier, ...],
        Field(min_length=1, max_length=30),
    ]


class CodeDiagnosisHypothesis(ContractModel):
    hypothesis_id: InvestigationIdentifier
    kind: NonEmptyString
    subject: NonEmptyString
    supporting_fact_ids: Annotated[
        tuple[InvestigationIdentifier, ...],
        Field(min_length=1, max_length=10),
    ]


class CodeDiagnosisInput(ContractModel):
    investigation_goal: NonEmptyString
    hypotheses: Annotated[
        tuple[CodeDiagnosisHypothesis, ...],
        Field(min_length=1, max_length=MAX_CODE_FINDINGS),
    ]
    facts: Annotated[FactSet, Field(max_length=30)]
    support_bundles: Annotated[
        tuple[CodeDiagnosisSupport, ...],
        Field(min_length=1, max_length=MAX_CODE_FINDINGS),
    ]
    locations: Annotated[
        tuple[CodeContextLocation, ...],
        Field(max_length=MAX_CODE_CONTEXT_LOCATIONS),
    ]


class CodeFindingCategory(StrEnum):
    CHANGED_CODE_NEAR_FAILURE = "changed_code_near_failure"
    ERROR_HANDLING_OR_NULL_PATH = "error_handling_or_null_path"
    INPUT_VALIDATION = "input_validation"
    STATE_OR_RESOURCE_LIFECYCLE = "state_or_resource_lifecycle"
    CONFIGURATION_OR_DEPLOYMENT = "configuration_or_deployment"


class SuspectedCodeFinding(ContractModel):
    finding_id: InvestigationIdentifier
    hypothesis_id: InvestigationIdentifier
    file_path: NonEmptyString


    location_evidence_id: InvestigationIdentifier
    category: CodeFindingCategory
    supporting_fact_ids: Annotated[
        tuple[InvestigationIdentifier, ...],
        Field(min_length=1, max_length=10),
    ]
    supporting_evidence_ids: Annotated[
        tuple[InvestigationIdentifier, ...],
        Field(min_length=1, max_length=30),
    ]
    explanation: CodeExplanation


class CodeDiagnosisOutput(ContractModel):
    candidates: Annotated[
        tuple[SuspectedCodeFinding, ...],
        Field(max_length=MAX_CODE_FINDINGS),
    ] = ()


class CodeDiagnosisMetadata(ContractModel):
    task: NonEmptyString = "code_diagnosis"
    provider: NonEmptyString
    model: NonEmptyString
    requested_model: NonEmptyString | None = None
    resolved_model: NonEmptyString | None = None
    prompt_id: NonEmptyString
    prompt_version: NonEmptyString
    token_usage: LLMTokenUsage | None = None


class GeneratedCodeFindings(ContractModel):
    candidates: tuple[SuspectedCodeFinding, ...]
    metadata: CodeDiagnosisMetadata


class CodeDiagnosisFailureCode(StrEnum):
    PROVIDER_FAILURE = "provider_failure"
    INVALID_RESPONSE = "invalid_response"
    CANDIDATE_SCHEMA_INVALID = "candidate_schema_invalid"


class CodeFindingValidationFailureCode(StrEnum):
    DUPLICATE_FINDING_ID = "duplicate_finding_id"
    DUPLICATE_REFERENCE = "duplicate_reference"
    UNKNOWN_HYPOTHESIS = "unknown_hypothesis"
    FILE_MISMATCH = "file_mismatch"
    UNKNOWN_SUPPORTING_FACT = "unknown_supporting_fact"
    HYPOTHESIS_SUPPORT_MISMATCH = "hypothesis_support_mismatch"
    UNKNOWN_SUPPORTING_EVIDENCE = "unknown_supporting_evidence"
    EVIDENCE_RELATIONSHIP_MISMATCH = "evidence_relationship_mismatch"
    LOCATION_NOT_OBSERVED = "location_not_observed"


class RejectedCodeFinding(ContractModel):
    candidate: SuspectedCodeFinding
    reason: CodeFindingValidationFailureCode


class ValidatedCodeFinding(ContractModel):
    finding_id: InvestigationIdentifier
    hypothesis_id: InvestigationIdentifier
    file_path: NonEmptyString
    line_number: Annotated[int, Field(strict=True, gt=0)] | None = None
    function_name: NonEmptyString | None = None
    hunk_evidence_id: InvestigationIdentifier | None = None
    category: CodeFindingCategory
    supporting_fact_ids: tuple[InvestigationIdentifier, ...]
    supporting_evidence_ids: tuple[InvestigationIdentifier, ...]


class CodeFindingValidationResult(ContractModel):
    accepted_findings: tuple[ValidatedCodeFinding, ...] = ()
    rejected_candidates: tuple[RejectedCodeFinding, ...] = ()


class FixProposalInput(ContractModel):
    finding: ValidatedCodeFinding
    hypothesis: CodeDiagnosisHypothesis
    facts: Annotated[FactSet, Field(min_length=1, max_length=10)]
    failure_error_category: NonEmptyString | None = None
    source_evidence_id: InvestigationIdentifier
    source_line_start: Annotated[int, Field(strict=True, gt=0)]
    source_line_end: Annotated[int, Field(strict=True, gt=0)]
    original_hunk: NonEmptyString
    supporting_fact_ids: tuple[InvestigationIdentifier, ...]
    supporting_evidence_ids: tuple[InvestigationIdentifier, ...]


class ProposedCodeFixCandidate(ContractModel):
    finding_id: InvestigationIdentifier
    file_path: NonEmptyString
    corrected_hunk: NonEmptyString
    failure_mechanism: CodeExplanation
    fix_strategy: CodeExplanation
    explanation: CodeExplanation
    supporting_fact_ids: Annotated[
        tuple[InvestigationIdentifier, ...], Field(min_length=1, max_length=10)
    ]
    supporting_evidence_ids: Annotated[
        tuple[InvestigationIdentifier, ...], Field(min_length=1, max_length=30)
    ]


class FixProposalOutput(ContractModel):
    candidate: ProposedCodeFixCandidate | None = None


class ProposedCodeFix(ContractModel):
    fix_id: InvestigationIdentifier
    finding_id: InvestigationIdentifier
    file_path: NonEmptyString
    function_name: NonEmptyString | None = None
    line_start: Annotated[int, Field(strict=True, gt=0)]
    line_end: Annotated[int, Field(strict=True, gt=0)]
    original_hunk: NonEmptyString
    corrected_hunk: NonEmptyString
    failure_mechanism: NonEmptyString
    fix_strategy: NonEmptyString
    explanation: NonEmptyString
    supporting_fact_ids: tuple[InvestigationIdentifier, ...]
    supporting_evidence_ids: tuple[InvestigationIdentifier, ...]


class CodeFixStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class CodeFixProposalFailureCode(StrEnum):
    PROVIDER_FAILURE = "provider_failure"
    INVALID_RESPONSE = "invalid_response"
    CANDIDATE_SCHEMA_INVALID = "candidate_schema_invalid"


class CodeFixValidationFailureCode(StrEnum):
    UNKNOWN_FINDING = "unknown_finding"
    FILE_MISMATCH = "file_mismatch"
    SUPPORT_MISMATCH = "support_mismatch"
    SOURCE_CONTEXT_MISMATCH = "source_context_mismatch"
    OVERSIZED_REPLACEMENT = "oversized_replacement"
    UNSUPPORTED_IMPORT = "unsupported_import"
    DIFF_MARKER_ARTIFACT = "diff_marker_artifact"


class RejectedCodeFix(ContractModel):
    candidate: ProposedCodeFixCandidate
    reason: CodeFixValidationFailureCode


class CodeFixValidationResult(ContractModel):
    accepted_fixes: tuple[ProposedCodeFix, ...] = ()
    rejected_candidates: tuple[RejectedCodeFix, ...] = ()


class DeveloperRecommendationCode(StrEnum):
    INSPECT_FAILURE_PATH = "inspect_failure_path"
    VALIDATE_ERROR_HANDLING = "validate_error_handling"
    VALIDATE_INPUT_BOUNDARY = "validate_input_boundary"
    INSPECT_RESOURCE_LIFECYCLE = "inspect_resource_lifecycle"
    COMPARE_DEPLOYMENT_CONFIGURATION = "compare_deployment_configuration"
    ADD_REGRESSION_TEST = "add_regression_test"


class DeveloperRecommendation(ContractModel):
    recommendation_id: InvestigationIdentifier
    code: DeveloperRecommendationCode
    message: NonEmptyString
    finding_id: InvestigationIdentifier
    supporting_fact_ids: tuple[InvestigationIdentifier, ...]
    supporting_evidence_ids: tuple[InvestigationIdentifier, ...]
