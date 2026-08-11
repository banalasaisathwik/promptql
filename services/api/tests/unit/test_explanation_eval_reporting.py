import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from app.evals.graders import aggregate_records, evaluate_thresholds
from app.evals.models import (
    EvalBaseline,
    EvalDatasetSplit,
    EvalModelSettings,
    EvalRunIdentity,
    EvalRunReport,
    ExplanationObservationRecord,
    ValidatorResult,
)
from app.evals.reporting import (
    baseline_from_report,
    compare_with_baseline,
    format_human_summary,
    load_baseline,
    write_baseline,
)
from app.explanations import LLMProviderName
from app.policy import MergeReadinessDecision, PolicyReasonCode


def identity(*, prompt_version: str = "v1") -> EvalRunIdentity:
    return EvalRunIdentity(
        prompt_id="merge-readiness-explanation",
        prompt_version=prompt_version,
        dataset_id="merge-readiness-development-v1",
        dataset_version="v1",
        dataset_split=EvalDatasetSplit.DEVELOPMENT,
        provider=LLMProviderName.FAKE,
        configured_model=None,
        model_settings=EvalModelSettings(
            request_timeout_seconds=30,
            max_output_tokens=512,
        ),
        samples_per_case=1,
        inter_request_delay_seconds=1,
    )


def passed_record(*, split: EvalDatasetSplit = EvalDatasetSplit.DEVELOPMENT):
    run_identity = identity().model_copy(update={"dataset_split": split})
    return ExplanationObservationRecord(
        case_id="ready",
        prompt_id=run_identity.prompt_id,
        prompt_version=run_identity.prompt_version,
        dataset_id=run_identity.dataset_id,
        dataset_version=run_identity.dataset_version,
        dataset_split=split,
        provider=run_identity.provider,
        configured_model=None,
        model_settings=run_identity.model_settings,
        sample_number=1,
        expected_decision=MergeReadinessDecision.READY,
        expected_reason_codes=(PolicyReasonCode.READY,),
        expected_action_codes=(),
        observed_decision=MergeReadinessDecision.READY,
        observed_reason_codes=(PolicyReasonCode.READY,),
        observed_action_codes=(),
        provider_success=True,
        candidate_returned=True,
        schema_valid=True,
        validator_result=ValidatorResult.PASSED,
        sanitized_failure_category=None,
        latency_ms=5,
        token_usage=None,
    )


def report(*, prompt_version: str = "v1") -> EvalRunReport:
    record = passed_record()
    metrics = aggregate_records((record,), planned_samples=1)
    now = datetime.now(UTC)
    return EvalRunReport(
        execution_completed=True,
        run_identity=identity(prompt_version=prompt_version),
        started_at=now,
        completed_at=now,
        git_commit="a" * 40,
        metrics=metrics,
        thresholds=evaluate_thresholds(
            metrics,
            (record,),
            dataset_split=EvalDatasetSplit.DEVELOPMENT,
        ),
        development_case_reliability=(),
    )


class ExplanationEvalReportingTests(unittest.TestCase):
    def test_baseline_round_trip_and_compatible_comparison(self) -> None:
        current_report = report()
        baseline = baseline_from_report(current_report)
        with tempfile.TemporaryDirectory() as temporary_directory:
            baseline_path = Path(temporary_directory) / "baseline.json"
            write_baseline(baseline_path, baseline)
            restored = load_baseline(baseline_path)

        comparison = compare_with_baseline(current_report, restored)
        self.assertEqual(restored, baseline)
        self.assertTrue(comparison.compatible)
        self.assertTrue(all(delta == 0 for delta in comparison.metric_deltas.values()))

    def test_incompatible_prompt_baseline_is_rejected(self) -> None:
        current_report = report(prompt_version="v2")
        previous_report = report(prompt_version="v1")
        baseline = EvalBaseline(
            created_at=previous_report.completed_at,
            git_commit=previous_report.git_commit,
            run_identity=previous_report.run_identity,
            metrics=previous_report.metrics,
        )

        comparison = compare_with_baseline(current_report, baseline)

        self.assertFalse(comparison.compatible)
        self.assertEqual(comparison.incompatibilities, ("prompt_version",))
        self.assertEqual(comparison.metric_deltas, {})

    def test_normal_holdout_summary_is_aggregate_only(self) -> None:
        record = passed_record(split=EvalDatasetSplit.HOLDOUT)
        metrics = aggregate_records((record,), planned_samples=1)
        now = datetime.now(UTC)
        holdout_identity = identity().model_copy(
            update={
                "dataset_id": "merge-readiness-holdout-v1",
                "dataset_split": EvalDatasetSplit.HOLDOUT,
            }
        )
        holdout_report = EvalRunReport(
            execution_completed=True,
            run_identity=holdout_identity,
            started_at=now,
            completed_at=now,
            git_commit=None,
            metrics=metrics,
            thresholds=evaluate_thresholds(
                metrics,
                (record,),
                dataset_split=EvalDatasetSplit.HOLDOUT,
            ),
            development_case_reliability=(),
        )

        normal = format_human_summary(
            holdout_report,
            (record,),
            include_holdout_details=False,
        )
        debug = format_human_summary(
            holdout_report,
            (record,),
            include_holdout_details=True,
        )

        self.assertNotIn("case_id", normal)
        self.assertNotIn("expected_reason_codes", normal)
        self.assertIn("holdout details (this holdout is now spent)", debug)
        self.assertIn('"case_id": "ready"', debug)


if __name__ == "__main__":
    unittest.main()
