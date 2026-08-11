from collections import Counter, defaultdict
from collections.abc import Sequence

from app.evals.models import (
    CaseReliability,
    CountRate,
    EvalAggregateMetrics,
    EvalDatasetSplit,
    EvalThresholdConfiguration,
    EvalThresholdResult,
    ExplanationObservationRecord,
    LatencySummary,
    TokenSummary,
    ValidatorResult,
)


V1_THRESHOLDS = EvalThresholdConfiguration(
    threshold_version="merge-readiness-explanation-v1",
    candidate_schema_valid_rate=1.0,
    candidate_decision_match_rate=1.0,
    candidate_exact_reason_set_match_rate=0.95,
    candidate_exact_action_set_match_rate=0.95,
    validator_pass_rate=0.95,
    maximum_provider_failure_rate=0.0,
)


def count_rate(numerator: int, denominator: int) -> CountRate:
    if numerator < 0 or denominator < 0 or numerator > denominator:
        raise ValueError("A metric count must be within its denominator.")
    rate = None if denominator == 0 else numerator / denominator
    return CountRate(numerator=numerator, denominator=denominator, rate=rate)


def _set_counts(expected: Sequence[object], observed: Sequence[object]) -> tuple[int, int, int]:
    expected_set = set(expected)
    observed_set = set(observed)
    true_positive = len(expected_set & observed_set)
    false_positive = len(observed_set - expected_set)
    false_negative = len(expected_set - observed_set)
    return true_positive, false_positive, false_negative


def _precision(true_positive: int, false_positive: int) -> float:
    denominator = true_positive + false_positive
    return 1.0 if denominator == 0 else true_positive / denominator


def _recall(true_positive: int, false_negative: int) -> float:
    denominator = true_positive + false_negative
    return 1.0 if denominator == 0 else true_positive / denominator


def record_decision_matches(record: ExplanationObservationRecord) -> bool:
    return record.observed_decision is record.expected_decision


def record_reason_set_matches(record: ExplanationObservationRecord) -> bool:
    return set(record.observed_reason_codes) == set(record.expected_reason_codes)


def record_action_set_matches(record: ExplanationObservationRecord) -> bool:
    return set(record.observed_action_codes) == set(record.expected_action_codes)


def record_quality_succeeds(record: ExplanationObservationRecord) -> bool:
    return (
        record.candidate_returned
        and record.schema_valid
        and record_decision_matches(record)
        and record_reason_set_matches(record)
        and record_action_set_matches(record)
        and record.validator_result is ValidatorResult.PASSED
    )


def aggregate_records(
    records: Sequence[ExplanationObservationRecord],
    *,
    planned_samples: int,
) -> EvalAggregateMetrics:
    if planned_samples < len(records):
        raise ValueError("Completed records cannot exceed planned samples.")

    candidates = tuple(record for record in records if record.candidate_returned)
    provider_success_count = sum(record.provider_success for record in records)
    schema_valid_count = sum(record.schema_valid for record in candidates)
    decision_match_count = sum(record_decision_matches(record) for record in candidates)
    reason_match_count = sum(record_reason_set_matches(record) for record in candidates)
    action_match_count = sum(record_action_set_matches(record) for record in candidates)
    validator_pass_count = sum(
        record.validator_result is ValidatorResult.PASSED for record in candidates
    )
    quality_success_count = sum(record_quality_succeeds(record) for record in candidates)

    reason_true_positive = 0
    reason_false_positive = 0
    reason_false_negative = 0
    action_true_positive = 0
    action_false_positive = 0
    action_false_negative = 0
    for record in candidates:
        reason_counts = _set_counts(
            record.expected_reason_codes,
            record.observed_reason_codes,
        )
        action_counts = _set_counts(
            record.expected_action_codes,
            record.observed_action_codes,
        )
        reason_true_positive += reason_counts[0]
        reason_false_positive += reason_counts[1]
        reason_false_negative += reason_counts[2]
        action_true_positive += action_counts[0]
        action_false_positive += action_counts[1]
        action_false_negative += action_counts[2]

    provider_failures = Counter(
        record.sanitized_failure_category or "unexpected"
        for record in records
        if not record.provider_success
    )
    latency_values = tuple(record.latency_ms for record in records)
    usage_values = tuple(
        record.token_usage for record in records if record.token_usage is not None
    )
    provider_total_values = tuple(
        usage.total_tokens for usage in usage_values if usage.total_tokens is not None
    )

    return EvalAggregateMetrics(
        planned_samples=planned_samples,
        attempted_samples=len(records),
        completed_samples=len(records),
        provider_success=count_rate(provider_success_count, len(records)),
        candidate_returned=count_rate(len(candidates), len(records)),
        candidate_schema_valid=count_rate(schema_valid_count, len(candidates)),
        candidate_decision_match=count_rate(decision_match_count, len(candidates)),
        candidate_exact_reason_set_match=count_rate(reason_match_count, len(candidates)),
        candidate_exact_action_set_match=count_rate(action_match_count, len(candidates)),
        reason_code_micro_precision=_precision(
            reason_true_positive,
            reason_false_positive,
        ),
        reason_code_micro_recall=_recall(
            reason_true_positive,
            reason_false_negative,
        ),
        action_code_micro_precision=_precision(
            action_true_positive,
            action_false_positive,
        ),
        action_code_micro_recall=_recall(
            action_true_positive,
            action_false_negative,
        ),
        validator_pass=count_rate(validator_pass_count, len(candidates)),
        candidate_end_to_end_quality=count_rate(
            quality_success_count,
            len(candidates),
        ),
        attempt_end_to_end_success=count_rate(
            quality_success_count,
            planned_samples,
        ),
        provider_failures_by_category=dict(sorted(provider_failures.items())),
        latency=LatencySummary(
            count=len(latency_values),
            minimum_ms=min(latency_values) if latency_values else None,
            maximum_ms=max(latency_values) if latency_values else None,
            mean_ms=(sum(latency_values) / len(latency_values) if latency_values else None),
        ),
        tokens=TokenSummary(
            samples_with_usage=len(usage_values),
            input_tokens=sum(usage.input_tokens for usage in usage_values),
            output_tokens=sum(usage.output_tokens for usage in usage_values),
            provider_total_tokens=sum(provider_total_values),
            samples_with_provider_total=len(provider_total_values),
        ),

        estimated_cost=None,
    )


def development_case_reliability(
    records: Sequence[ExplanationObservationRecord],
) -> tuple[CaseReliability, ...]:
    grouped: dict[str, list[ExplanationObservationRecord]] = defaultdict(list)
    for record in records:
        grouped[record.case_id].append(record)

    reliability: list[CaseReliability] = []
    for case_id, case_records in grouped.items():
        candidates = tuple(record for record in case_records if record.candidate_returned)
        quality_successes = sum(record_quality_succeeds(record) for record in candidates)
        attempt_successes = sum(record_quality_succeeds(record) for record in case_records)
        reliability.append(
            CaseReliability(
                case_id=case_id,
                attempts=len(case_records),
                candidate_quality_successes=quality_successes,
                attempt_successes=attempt_successes,
                candidate_quality_rate=(
                    quality_successes / len(candidates) if candidates else None
                ),
                attempt_success_rate=(
                    attempt_successes / len(case_records) if case_records else None
                ),
            )
        )
    return tuple(reliability)


def evaluate_thresholds(
    metrics: EvalAggregateMetrics,
    records: Sequence[ExplanationObservationRecord],
    *,
    dataset_split: EvalDatasetSplit,
    thresholds: EvalThresholdConfiguration = V1_THRESHOLDS,
) -> EvalThresholdResult:
    quality_rates = (
        ("candidate_schema_valid_rate", metrics.candidate_schema_valid.rate, thresholds.candidate_schema_valid_rate),
        ("candidate_decision_match_rate", metrics.candidate_decision_match.rate, thresholds.candidate_decision_match_rate),
        ("candidate_exact_reason_set_match_rate", metrics.candidate_exact_reason_set_match.rate, thresholds.candidate_exact_reason_set_match_rate),
        ("candidate_exact_action_set_match_rate", metrics.candidate_exact_action_set_match.rate, thresholds.candidate_exact_action_set_match_rate),
        ("validator_pass_rate", metrics.validator_pass.rate, thresholds.validator_pass_rate),
    )
    failed_quality_checks = [
        name for name, actual, minimum in quality_rates if actual is None or actual < minimum
    ]
    critical_holdout_failure = (
        dataset_split is EvalDatasetSplit.HOLDOUT
        and any(
            record.candidate_returned and not record_quality_succeeds(record)
            for record in records
        )
    )
    if critical_holdout_failure:
        failed_quality_checks.append("critical_holdout_quality_failure")

    provider_failure_rate = 1.0 - (metrics.provider_success.rate or 0.0)
    failed_operational_checks = (
        ("provider_failure_rate",)
        if provider_failure_rate > thresholds.maximum_provider_failure_rate
        else ()
    )
    quality_passed = not failed_quality_checks
    operational_passed = not failed_operational_checks
    return EvalThresholdResult(
        threshold_version=thresholds.threshold_version,
        quality_passed=quality_passed,
        operational_passed=operational_passed,
        release_passed=quality_passed and operational_passed,
        critical_holdout_quality_failure=critical_holdout_failure,
        failed_quality_checks=tuple(failed_quality_checks),
        failed_operational_checks=failed_operational_checks,
    )
