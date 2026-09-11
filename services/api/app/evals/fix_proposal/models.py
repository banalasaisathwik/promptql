from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.connectors.models import ContractModel, NonEmptyString
from app.evals.models import CountRate, LatencySummary, TokenSummary
from app.explanations import LLMProviderName, LLMTokenUsage
from app.investigations.code_diagnosis import CodeFixValidationFailureCode
from app.investigations.models import Evidence


class FixProposalEvalCategory(StrEnum):
    KEY_ERROR = "key_error"
    NONE_DEREFERENCE = "none_dereference"
    INPUT_BOUNDARY = "input_boundary"
    CONFIGURATION_MISMATCH = "configuration_mismatch"
    INSUFFICIENT_CONTEXT = "insufficient_context"


class FixProposalEvalCase(ContractModel):
    case_id: NonEmptyString
    category: FixProposalEvalCategory
    evidence: tuple[Evidence, ...] = Field(min_length=1)
    hypothesis_subject: NonEmptyString
    expected_file_path: NonEmptyString
    expect_fix_available: bool


    syntax_checkable: bool = True


    grounding_keywords: tuple[NonEmptyString, ...] = Field(min_length=1)
    buggy_line_substring: NonEmptyString | None = None
    fixed_line_substring: NonEmptyString | None = None


class FixProposalEvalDataset(ContractModel):
    dataset_id: NonEmptyString
    dataset_version: NonEmptyString
    cases: tuple[FixProposalEvalCase, ...] = Field(min_length=1)


class FixProposalProviderBoundaryObservation(ContractModel):
    attempted: bool
    provider_success: bool
    schema_valid: bool
    sanitized_failure_category: NonEmptyString | None = None
    latency_ms: int = Field(ge=0)
    token_usage: LLMTokenUsage | None = None
    resolved_model: NonEmptyString | None = None


class FixProposalCaseObservation(ContractModel):
    case_id: NonEmptyString
    category: FixProposalEvalCategory
    sample_number: int = Field(ge=1)
    provider: LLMProviderName
    requested_model: NonEmptyString
    boundary: FixProposalProviderBoundaryObservation
    candidate_returned: bool
    accepted: bool
    rejection_reason: CodeFixValidationFailureCode | None = None
    correct_file: bool | None = None
    correct_hunk_or_location: bool | None = None
    failure_mechanism_grounded: bool | None = None
    minimal_edit: bool | None = None
    unsupported_identifier_count: int = Field(ge=0)
    corrected_identifier_count: int = Field(ge=0)
    syntax_valid: bool | None = None
    fix_available_when_expected: bool | None = None
    abstains_when_fix_not_grounded: bool | None = None
    latency_ms: int = Field(ge=0)


class FixProposalEvalMetrics(ContractModel):
    planned_samples: int = Field(ge=0)
    completed_samples: int = Field(ge=0)
    provider_success: CountRate
    schema_valid: CountRate
    correct_file: CountRate
    correct_hunk_or_location: CountRate
    failure_mechanism_grounded: CountRate
    minimal_edit: CountRate
    unsupported_identifier_rate: float = Field(ge=0, le=1)
    syntax_valid: CountRate
    fix_available_when_expected: CountRate
    abstains_when_fix_not_grounded: CountRate
    provider_failures_by_category: dict[str, int]
    latency: LatencySummary
    tokens: TokenSummary


class FixProposalEvalRunIdentity(ContractModel):
    dataset_id: NonEmptyString
    dataset_version: NonEmptyString
    provider: LLMProviderName
    requested_model: NonEmptyString
    samples_per_case: int = Field(ge=1)
    inter_request_delay_seconds: float = Field(ge=0)


class FixProposalEvalReport(ContractModel):
    execution_completed: bool
    run_identity: FixProposalEvalRunIdentity
    started_at: datetime
    completed_at: datetime
    git_commit: NonEmptyString | None
    metrics: FixProposalEvalMetrics
    release_passed: bool
    failed_checks: tuple[NonEmptyString, ...]
