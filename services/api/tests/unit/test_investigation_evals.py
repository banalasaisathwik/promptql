import asyncio
import tempfile
import unittest
from pathlib import Path

from app.config import LLMProvider, LLMSettings
from app.evals.investigations.cases import build_investigation_eval_dataset
from app.evals.investigations.evaluation import execute_investigation_eval
from app.evals.investigations.runner import (
    MAX_PROVIDER_CALLS_PER_SAMPLE,
    build_investigation_eval_identity,
    run_investigation_eval,
)
from app.evals.models import EvalDatasetSplit
from app.explanations import (
    FakeLLMClient,
    LLMProviderError,
    LLMProviderFailureCategory,
    LLMProviderName,
    LLMStructuredResponse,
)


def _settings() -> LLMSettings:
    return LLMSettings(
        provider=LLMProvider.FAKE,
        api_key=None,
        model=None,
        request_timeout_seconds=30,
        max_output_tokens=512,
    )


def _identity(split: EvalDatasetSplit, *, samples: int = 1):
    dataset = build_investigation_eval_dataset(split)
    return dataset, build_investigation_eval_identity(
        _settings(),
        dataset,
        samples_per_case=samples,
        inter_request_delay_seconds=0,
    )


class ProviderFailureClient(FakeLLMClient):
    async def generate_typed(self, request):
        raise LLMProviderError(LLMProviderFailureCategory.RATE_LIMIT)


class SchemaInvalidClient(FakeLLMClient):
    async def generate_typed(self, request):
        return LLMStructuredResponse(output={"candidates": "invalid"})


class InvestigationEvalDatasetTests(unittest.TestCase):
    def test_development_and_holdout_are_versioned_reference_cases(self) -> None:
        development = build_investigation_eval_dataset(
            EvalDatasetSplit.DEVELOPMENT
        )
        holdout = build_investigation_eval_dataset(EvalDatasetSplit.HOLDOUT)

        self.assertNotEqual(development.dataset_id, holdout.dataset_id)
        self.assertEqual(development.dataset_version, holdout.dataset_version)
        self.assertNotEqual(
            development.cases[0].request.question,
            holdout.cases[0].request.question,
        )
        self.assertEqual(
            development.cases[0].relevant_evidence_ids,
            holdout.cases[0].relevant_evidence_ids,
        )
        self.assertEqual(MAX_PROVIDER_CALLS_PER_SAMPLE, 8)


class InvestigationEvalExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_eval_separates_component_and_trajectory_checks(self) -> None:
        dataset, identity = _identity(EvalDatasetSplit.DEVELOPMENT)
        client = FakeLLMClient()

        observations, report = await execute_investigation_eval(
            dataset,
            run_identity=identity,
            planner_client=client,
            hypothesis_client=client,
            code_diagnosis_client=client,
            git_commit="abc1234",
            sleep=self._no_sleep,
        )

        self.assertEqual(len(observations), 1)
        observation = observations[0]
        self.assertTrue(observation.planner.provider_success)
        self.assertTrue(observation.planner.schema_valid)
        self.assertTrue(observation.components.planner_valid)
        self.assertTrue(observation.components.planner_useful)
        self.assertTrue(observation.components.unsupported_claims_rejected)
        self.assertTrue(observation.trajectory.allowed_tools_only)
        self.assertTrue(observation.trajectory.all_plans_validated)
        self.assertTrue(observation.trajectory.budget_respected)
        self.assertTrue(observation.trajectory.round_limit_respected)
        self.assertTrue(observation.trajectory.relevant_evidence_discovered)
        self.assertTrue(observation.trajectory.facts_grounded)
        self.assertTrue(observation.trajectory.hypotheses_grounded)
        self.assertTrue(observation.trajectory.code_findings_grounded)
        self.assertTrue(observation.trajectory.sensible_termination)
        self.assertEqual(
            observation.trajectory.deterministic_baseline_evidence_recall,
            1,
        )
        self.assertEqual(observation.trajectory.adaptive_evidence_recall, 1)
        self.assertTrue(report.release_passed)
        self.assertEqual(report.metrics.provider_success.denominator, 3)
        self.assertEqual(report.metrics.provider_success.rate, 1)
        self.assertEqual(report.metrics.component_quality.rate, 1)
        self.assertEqual(report.metrics.trajectory_quality.rate, 1)
        self.assertIsNone(report.metrics.estimated_cost)

    async def test_provider_failure_is_not_reported_as_reasoning_quality(self) -> None:
        dataset, identity = _identity(EvalDatasetSplit.DEVELOPMENT)
        client = ProviderFailureClient()

        observations, report = await execute_investigation_eval(
            dataset,
            run_identity=identity,
            planner_client=client,
            hypothesis_client=client,
            code_diagnosis_client=client,
            sleep=self._no_sleep,
        )

        self.assertFalse(observations[0].planner.provider_success)
        self.assertFalse(observations[0].hypothesis.provider_success)
        self.assertFalse(observations[0].code_diagnosis.attempted)
        self.assertEqual(report.metrics.provider_success.rate, 0)
        self.assertIsNone(report.metrics.schema_valid.rate)
        self.assertEqual(
            report.metrics.provider_failures_by_stage_and_category,
            {
                "hypothesis:rate_limit": 1,
                "planner:rate_limit": 1,
            },
        )
        self.assertIn("provider_success", report.failed_checks)
        self.assertIn("component_quality", report.failed_checks)

    async def test_schema_failure_keeps_provider_execution_success_separate(self) -> None:
        dataset, identity = _identity(EvalDatasetSplit.DEVELOPMENT)
        client = SchemaInvalidClient()

        observations, report = await execute_investigation_eval(
            dataset,
            run_identity=identity,
            planner_client=client,
            hypothesis_client=client,
            code_diagnosis_client=client,
            sleep=self._no_sleep,
        )

        self.assertTrue(observations[0].planner.provider_success)
        self.assertFalse(observations[0].planner.schema_valid)
        self.assertEqual(report.metrics.provider_success.rate, 1)
        self.assertEqual(report.metrics.schema_valid.rate, 0)
        self.assertNotIn("provider_success", report.failed_checks)
        self.assertIn("schema_valid", report.failed_checks)

    async def test_repeated_holdout_samples_are_independent_and_paced(self) -> None:
        dataset, identity = _identity(EvalDatasetSplit.HOLDOUT, samples=2)
        client = FakeLLMClient()
        sleeps = []

        async def record_sleep(delay: float) -> None:
            sleeps.append(delay)

        observations, report = await execute_investigation_eval(
            dataset,
            run_identity=identity,
            planner_client=client,
            hypothesis_client=client,
            code_diagnosis_client=client,
            sleep=record_sleep,
        )

        self.assertEqual([item.sample_number for item in observations], [1, 2])
        self.assertEqual(sleeps, [0])
        self.assertEqual(report.metrics.planned_samples, 2)
        self.assertEqual(report.metrics.completed_samples, 2)
        self.assertTrue(report.release_passed)

    async def test_report_artifact_contains_aggregates_not_incident_payloads(self) -> None:
        dataset = build_investigation_eval_dataset(
            EvalDatasetSplit.DEVELOPMENT
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_path = Path(temporary_directory) / "report.json"

            observations, report = await run_investigation_eval(
                _settings(),
                dataset,
                samples_per_case=1,
                inter_request_delay_seconds=0,
                acknowledge_paid_calls=False,
                fake_dry_run=True,
                report_path=report_path,
                sleep=self._no_sleep,
            )

            artifact = report_path.read_text(encoding="utf-8")
        self.assertEqual(len(observations), 1)
        self.assertTrue(report.release_passed)
        self.assertNotIn(dataset.cases[0].request.question, artifact)
        self.assertNotIn("return total or 0", artifact)
        self.assertNotIn("Adversarial eval candidate", artifact)
        self.assertNotIn("authorization", artifact.lower())

    @staticmethod
    async def _no_sleep(delay: float) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
