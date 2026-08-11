from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.connectors.models import ContractModel, NonEmptyString
from app.explanations.models import LLMProviderName, LLMTokenUsage
from app.policy import (
    MergeReadinessDecision,
    PendingActionCode,
    PolicyReasonCode,
)


class ValidatorResult(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"


class EvalDatasetSplit(StrEnum):
    DEVELOPMENT = "development"
    HOLDOUT = "holdout"


class EvalModelSettings(ContractModel):
    request_timeout_seconds: float = Field(gt=0)
    max_output_tokens: int = Field(gt=0)


class CountRate(ContractModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    rate: float | None = Field(default=None, ge=0, le=1)


class LatencySummary(ContractModel):
    count: int = Field(ge=0)
    minimum_ms: int | None = Field(default=None, ge=0)
    maximum_ms: int | None = Field(default=None, ge=0)
    mean_ms: float | None = Field(default=None, ge=0)


class TokenSummary(ContractModel):
    samples_with_usage: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    provider_total_tokens: int = Field(ge=0)
    samples_with_provider_total: int = Field(ge=0)


class CaseReliability(ContractModel):
    case_id: NonEmptyString
    attempts: int = Field(ge=0)
    candidate_quality_successes: int = Field(ge=0)
    attempt_successes: int = Field(ge=0)
    candidate_quality_rate: float | None = Field(default=None, ge=0, le=1)
    attempt_success_rate: float | None = Field(default=None, ge=0, le=1)


class EvalAggregateMetrics(ContractModel):
    planned_samples: int = Field(ge=0)
    attempted_samples: int = Field(ge=0)
    completed_samples: int = Field(ge=0)
    provider_success: CountRate
    candidate_returned: CountRate
    candidate_schema_valid: CountRate
    candidate_decision_match: CountRate
    candidate_exact_reason_set_match: CountRate
    candidate_exact_action_set_match: CountRate
    reason_code_micro_precision: float = Field(ge=0, le=1)
    reason_code_micro_recall: float = Field(ge=0, le=1)
    action_code_micro_precision: float = Field(ge=0, le=1)
    action_code_micro_recall: float = Field(ge=0, le=1)
    validator_pass: CountRate
    candidate_end_to_end_quality: CountRate
    attempt_end_to_end_success: CountRate
    provider_failures_by_category: dict[str, int]
    latency: LatencySummary
    tokens: TokenSummary
    estimated_cost: float | None = Field(default=None, ge=0)


class EvalThresholdConfiguration(ContractModel):
    threshold_version: NonEmptyString
    candidate_schema_valid_rate: float = Field(ge=0, le=1)
    candidate_decision_match_rate: float = Field(ge=0, le=1)
    candidate_exact_reason_set_match_rate: float = Field(ge=0, le=1)
    candidate_exact_action_set_match_rate: float = Field(ge=0, le=1)
    validator_pass_rate: float = Field(ge=0, le=1)
    maximum_provider_failure_rate: float = Field(ge=0, le=1)


class EvalThresholdResult(ContractModel):
    threshold_version: NonEmptyString
    quality_passed: bool
    operational_passed: bool
    release_passed: bool
    critical_holdout_quality_failure: bool
    failed_quality_checks: tuple[NonEmptyString, ...]
    failed_operational_checks: tuple[NonEmptyString, ...]


class EvalRunIdentity(ContractModel):
    prompt_id: NonEmptyString
    prompt_version: NonEmptyString
    dataset_id: NonEmptyString
    dataset_version: NonEmptyString
    dataset_split: EvalDatasetSplit
    provider: LLMProviderName
    configured_model: NonEmptyString | None
    model_settings: EvalModelSettings
    samples_per_case: int = Field(ge=1)
    inter_request_delay_seconds: float = Field(ge=0)


class EvalRunReport(ContractModel):
    execution_completed: bool
    run_identity: EvalRunIdentity
    started_at: datetime
    completed_at: datetime
    git_commit: NonEmptyString | None
    metrics: EvalAggregateMetrics
    thresholds: EvalThresholdResult
    development_case_reliability: tuple[CaseReliability, ...]
    baseline_comparison: EvalBaselineComparison | None = None


class EvalBaseline(ContractModel):
    created_at: datetime
    git_commit: NonEmptyString | None
    run_identity: EvalRunIdentity
    metrics: EvalAggregateMetrics


class EvalBaselineComparison(ContractModel):
    compatible: bool
    incompatibilities: tuple[NonEmptyString, ...]
    metric_deltas: dict[str, float]


class ExplanationObservationRecord(ContractModel):
    case_id: NonEmptyString
    prompt_id: NonEmptyString
    prompt_version: NonEmptyString
    dataset_id: NonEmptyString
    dataset_version: NonEmptyString
    dataset_split: EvalDatasetSplit
    provider: LLMProviderName
    configured_model: NonEmptyString | None
    model_settings: EvalModelSettings
    sample_number: int = Field(ge=1)

    expected_decision: MergeReadinessDecision
    expected_reason_codes: tuple[PolicyReasonCode, ...] = Field(max_length=50)
    expected_action_codes: tuple[PendingActionCode, ...] = Field(max_length=50)

    observed_decision: MergeReadinessDecision | None
    observed_reason_codes: tuple[PolicyReasonCode, ...] = Field(max_length=50)
    observed_action_codes: tuple[PendingActionCode, ...] = Field(max_length=50)

    provider_success: bool
    candidate_returned: bool
    schema_valid: bool
    validator_result: ValidatorResult
    sanitized_failure_category: NonEmptyString | None
    latency_ms: int = Field(ge=0)
    token_usage: LLMTokenUsage | None
