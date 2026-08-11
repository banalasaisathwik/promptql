import unittest

from app.evals.graders import (
    aggregate_records,
    development_case_reliability,
    evaluate_thresholds,
    record_action_set_matches,
    record_quality_succeeds,
    record_reason_set_matches,
)
from app.evals.models import (
    EvalDatasetSplit,
    EvalModelSettings,
    ExplanationObservationRecord,
    ValidatorResult,
)
from app.explanations import LLMProviderName, LLMTokenUsage
from app.policy import MergeReadinessDecision, PendingActionCode, PolicyReasonCode


def observation(
    *,
    case_id: str = "case-a",
    sample_number: int = 1,
    expected_reasons=(PolicyReasonCode.PR_IS_DRAFT,),
    observed_reasons=(PolicyReasonCode.PR_IS_DRAFT,),
    expected_actions=(PendingActionCode.MARK_PR_READY,),
    observed_actions=(PendingActionCode.MARK_PR_READY,),
    provider_success: bool = True,
    candidate_returned: bool = True,
    schema_valid: bool = True,
    validator_result: ValidatorResult = ValidatorResult.PASSED,
    failure: str | None = None,
    latency_ms: int = 10,
    token_usage: LLMTokenUsage | None = None,
) -> ExplanationObservationRecord:
    return ExplanationObservationRecord(
        case_id=case_id,
        prompt_id="merge-readiness-explanation",
        prompt_version="v1",
        dataset_id="merge-readiness-development-v1",
        dataset_version="v1",
        dataset_split=EvalDatasetSplit.DEVELOPMENT,
        provider=LLMProviderName.FAKE,
        configured_model=None,
        model_settings=EvalModelSettings(
            request_timeout_seconds=30,
            max_output_tokens=512,
        ),
        sample_number=sample_number,
        expected_decision=MergeReadinessDecision.BLOCKED,
        expected_reason_codes=expected_reasons,
        expected_action_codes=expected_actions,
        observed_decision=(
            MergeReadinessDecision.BLOCKED if candidate_returned else None
        ),
        observed_reason_codes=observed_reasons if candidate_returned else (),
        observed_action_codes=observed_actions if candidate_returned else (),
        provider_success=provider_success,
        candidate_returned=candidate_returned,
        schema_valid=schema_valid,
        validator_result=validator_result,
        sanitized_failure_category=failure,
        latency_ms=latency_ms,
        token_usage=token_usage,
    )


class ExplanationEvalGraderTests(unittest.TestCase):
    def test_exact_set_ignores_order_but_validator_still_detects_duplicates(self) -> None:
        duplicate = observation(
            expected_reasons=(
                PolicyReasonCode.PR_IS_DRAFT,
                PolicyReasonCode.MERGE_CONFLICT,
            ),
            observed_reasons=(
                PolicyReasonCode.MERGE_CONFLICT,
                PolicyReasonCode.PR_IS_DRAFT,
                PolicyReasonCode.PR_IS_DRAFT,
            ),
            validator_result=ValidatorResult.FAILED,
            failure="duplicate_reason",
        )

        self.assertTrue(record_reason_set_matches(duplicate))
        self.assertTrue(record_action_set_matches(duplicate))
        self.assertFalse(record_quality_succeeds(duplicate))

    def test_empty_action_sets_have_perfect_exact_precision_and_recall(self) -> None:
        ready = observation(
            expected_reasons=(PolicyReasonCode.READY,),
            observed_reasons=(PolicyReasonCode.READY,),
            expected_actions=(),
            observed_actions=(),
        )
        metrics = aggregate_records((ready,), planned_samples=1)

        self.assertTrue(record_action_set_matches(ready))
        self.assertEqual(metrics.action_code_micro_precision, 1.0)
        self.assertEqual(metrics.action_code_micro_recall, 1.0)
        self.assertEqual(metrics.candidate_exact_action_set_match.rate, 1.0)

    def test_micro_precision_and_recall_use_set_counts(self) -> None:
        partial = observation(
            expected_reasons=(
                PolicyReasonCode.PR_IS_DRAFT,
                PolicyReasonCode.MERGE_CONFLICT,
            ),
            observed_reasons=(
                PolicyReasonCode.PR_IS_DRAFT,
                PolicyReasonCode.CI_CHECK_FAILED,
            ),
            validator_result=ValidatorResult.FAILED,
            failure="unsupported_reason",
        )
        metrics = aggregate_records((partial,), planned_samples=1)

        self.assertEqual(metrics.reason_code_micro_precision, 0.5)
        self.assertEqual(metrics.reason_code_micro_recall, 0.5)
        self.assertEqual(metrics.candidate_exact_reason_set_match.rate, 0.0)

    def test_provider_failures_use_attempt_but_not_candidate_denominators(self) -> None:
        passed = observation()
        rate_limited = observation(
            case_id="case-b",
            provider_success=False,
            candidate_returned=False,
            schema_valid=False,
            validator_result=ValidatorResult.NOT_RUN,
            failure="rate_limit",
        )
        metrics = aggregate_records((passed, rate_limited), planned_samples=2)

        self.assertEqual(metrics.provider_success.model_dump(), {
            "numerator": 1,
            "denominator": 2,
            "rate": 0.5,
        })
        self.assertEqual(metrics.candidate_schema_valid.denominator, 1)
        self.assertEqual(metrics.candidate_schema_valid.rate, 1.0)
        self.assertEqual(metrics.attempt_end_to_end_success.rate, 0.5)
        self.assertEqual(metrics.provider_failures_by_category, {"rate_limit": 1})

    def test_schema_and_validator_failures_are_distinct_candidate_failures(self) -> None:
        schema_failure = observation(
            case_id="schema",
            schema_valid=False,
            validator_result=ValidatorResult.NOT_RUN,
            failure="invalid_structure",
        )
        validator_failure = observation(
            case_id="validator",
            validator_result=ValidatorResult.FAILED,
            failure="missing_required_reason",
        )
        metrics = aggregate_records(
            (schema_failure, validator_failure),
            planned_samples=2,
        )

        self.assertEqual(metrics.provider_success.rate, 1.0)
        self.assertEqual(metrics.candidate_schema_valid.rate, 0.5)
        self.assertEqual(metrics.validator_pass.rate, 0.0)
        self.assertEqual(metrics.candidate_end_to_end_quality.rate, 0.0)
        self.assertEqual(metrics.provider_failures_by_category, {})

    def test_repeated_samples_and_per_case_reliability_remain_separate(self) -> None:
        records = (
            observation(case_id="case-a", sample_number=1),
            observation(case_id="case-a", sample_number=2),
            observation(
                case_id="case-a",
                sample_number=3,
                provider_success=False,
                candidate_returned=False,
                schema_valid=False,
                validator_result=ValidatorResult.NOT_RUN,
                failure="rate_limit",
            ),
        )
        reliability = development_case_reliability(records)

        self.assertEqual(len(reliability), 1)
        self.assertEqual(reliability[0].attempts, 3)
        self.assertEqual(reliability[0].candidate_quality_rate, 1.0)
        self.assertAlmostEqual(reliability[0].attempt_success_rate or 0, 2 / 3)

    def test_latency_and_token_totals_preserve_provider_total_independently(self) -> None:
        records = (
            observation(
                latency_ms=10,
                token_usage=LLMTokenUsage(
                    input_tokens=3,
                    output_tokens=2,
                    total_tokens=20,
                ),
            ),
            observation(
                case_id="case-b",
                latency_ms=30,
                token_usage=LLMTokenUsage(
                    input_tokens=4,
                    output_tokens=1,
                    total_tokens=None,
                ),
            ),
        )
        metrics = aggregate_records(records, planned_samples=2)

        self.assertEqual(metrics.latency.minimum_ms, 10)
        self.assertEqual(metrics.latency.maximum_ms, 30)
        self.assertEqual(metrics.latency.mean_ms, 20)
        self.assertEqual(metrics.tokens.input_tokens, 7)
        self.assertEqual(metrics.tokens.output_tokens, 3)
        self.assertEqual(metrics.tokens.provider_total_tokens, 20)
        self.assertEqual(metrics.tokens.samples_with_provider_total, 1)

    def test_thresholds_separate_quality_from_provider_operation(self) -> None:
        passed = observation()
        rate_limited = observation(
            case_id="case-b",
            provider_success=False,
            candidate_returned=False,
            schema_valid=False,
            validator_result=ValidatorResult.NOT_RUN,
            failure="rate_limit",
        )
        metrics = aggregate_records((passed, rate_limited), planned_samples=2)
        result = evaluate_thresholds(
            metrics,
            (passed, rate_limited),
            dataset_split=EvalDatasetSplit.DEVELOPMENT,
        )

        self.assertTrue(result.quality_passed)
        self.assertFalse(result.operational_passed)
        self.assertFalse(result.release_passed)
        self.assertEqual(result.failed_operational_checks, ("provider_failure_rate",))

    def test_holdout_candidate_quality_failure_is_critical(self) -> None:
        bad_candidate = observation(
            validator_result=ValidatorResult.FAILED,
            failure="missing_required_reason",
        )
        metrics = aggregate_records((bad_candidate,), planned_samples=1)
        result = evaluate_thresholds(
            metrics,
            (bad_candidate,),
            dataset_split=EvalDatasetSplit.HOLDOUT,
        )

        self.assertTrue(result.critical_holdout_quality_failure)
        self.assertIn("critical_holdout_quality_failure", result.failed_quality_checks)


if __name__ == "__main__":
    unittest.main()
