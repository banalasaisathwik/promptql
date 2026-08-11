import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.config import LLMProvider, LLMSettings
from app.evals.cases import (
    ExplanationEvalDataset,
    build_development_dataset,
    build_holdout_dataset,
)
from app.evals.models import EvalDatasetSplit, ValidatorResult
from app.evals.reporting import DETAIL_FIELDS
from app.evals.runner import (
    DEFAULT_INTER_REQUEST_DELAY_SECONDS,
    DEFAULT_SAMPLES_PER_CASE,
    EvalArtifactPaths,
    PaidCallAcknowledgementError,
    _run_cli,
    build_run_identity,
    eval_exit_code,
    execute_eval,
    run_repeated_samples,
)
from app.explanations import (
    FakeLLMClient,
    GeneratedExplanation,
    LLMProviderError,
    LLMProviderFailureCategory,
    LLMProviderName,
    LLMStructuredResponse,
)
from app.evals.observation import observe_case


def fake_settings() -> LLMSettings:
    return LLMSettings(
        provider=LLMProvider.FAKE,
        api_key=None,
        model=None,
        request_timeout_seconds=30,
        max_output_tokens=512,
    )


def real_settings() -> LLMSettings:
    return LLMSettings(
        provider=LLMProvider.OPENAI,
        api_key="test-secret-never-serialized",
        model="configured-test-model",
        request_timeout_seconds=30,
        max_output_tokens=512,
    )


class CountingFakeClient(FakeLLMClient):
    def __init__(self) -> None:
        self.call_count = 0

    async def generate_structured(self, explanation_input):
        self.call_count += 1
        return await super().generate_structured(explanation_input)


class OneRateLimitClient(FakeLLMClient):
    def __init__(self) -> None:
        self.call_count = 0

    async def generate_structured(self, explanation_input):
        self.call_count += 1
        if self.call_count == 2:
            raise LLMProviderError(LLMProviderFailureCategory.RATE_LIMIT)
        return await super().generate_structured(explanation_input)


class AlwaysRateLimitedOpenAIClient:
    provider = LLMProviderName.OPENAI

    async def generate_structured(self, _explanation_input):
        raise LLMProviderError(LLMProviderFailureCategory.RATE_LIMIT)


class InvalidCandidateClient:
    provider = LLMProviderName.FAKE

    async def generate_structured(self, _explanation_input):
        return LLMStructuredResponse(output={"unsupported": "shape"})


class DuplicateClaimClient:
    provider = LLMProviderName.FAKE

    async def generate_structured(self, explanation_input):
        generated = GeneratedExplanation(
            decision=explanation_input.decision,
            summary="discarded duplicate test prose",
            reason_codes=(
                explanation_input.primary_reason_code,
                explanation_input.primary_reason_code,
            ),
            action_codes=(),
        )
        return LLMStructuredResponse(output=generated.model_dump(mode="json"))


class UnexpectedFailureClient:
    provider = LLMProviderName.FAKE

    async def generate_structured(self, _explanation_input):
        raise RuntimeError("raw secret exception must not escape")


class ExplanationEvalRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        development = await build_development_dataset()
        self.small_development = ExplanationEvalDataset(
            dataset_id=development.dataset_id,
            dataset_version=development.dataset_version,
            split=development.split,
            cases=development.cases[:2],
        )

    def test_safe_repeated_sampling_defaults_are_explicit(self) -> None:
        self.assertEqual(DEFAULT_SAMPLES_PER_CASE, 3)
        self.assertEqual(DEFAULT_INTER_REQUEST_DELAY_SECONDS, 1.0)

    async def test_repeated_samples_are_paced_between_calls_without_retry(self) -> None:
        client = OneRateLimitClient()
        sleeps: list[float] = []

        async def record_sleep(delay: float) -> None:
            sleeps.append(delay)

        identity = build_run_identity(
            fake_settings(),
            self.small_development,
            samples_per_case=2,
            inter_request_delay_seconds=0.25,
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            records = await run_repeated_samples(
                self.small_development.cases,
                client,
                run_identity=identity,
                observations_path=Path(temporary_directory) / "observations.jsonl",
                include_details=True,
                sleep=record_sleep,
            )

        self.assertEqual(client.call_count, 4)
        self.assertEqual(len(records), 4)
        self.assertEqual(sleeps, [0.25, 0.25, 0.25])
        self.assertEqual(records[1].sanitized_failure_category, "rate_limit")
        self.assertIs(records[1].validator_result, ValidatorResult.NOT_RUN)
        self.assertTrue(records[2].provider_success)

    async def test_schema_validator_and_unexpected_failures_are_classified(self) -> None:
        ready_case = self.small_development.cases[0]
        identity = build_run_identity(
            fake_settings(),
            self.small_development,
            samples_per_case=1,
            inter_request_delay_seconds=0,
        )

        invalid = await observe_case(
            ready_case,
            InvalidCandidateClient(),
            run_identity=identity,
            sample_number=1,
        )
        duplicate = await observe_case(
            ready_case,
            DuplicateClaimClient(),
            run_identity=identity,
            sample_number=1,
        )
        unexpected = await observe_case(
            ready_case,
            UnexpectedFailureClient(),
            run_identity=identity,
            sample_number=1,
        )

        self.assertTrue(invalid.provider_success)
        self.assertTrue(invalid.candidate_returned)
        self.assertFalse(invalid.schema_valid)
        self.assertEqual(invalid.sanitized_failure_category, "invalid_structure")
        self.assertTrue(duplicate.schema_valid)
        self.assertIs(duplicate.validator_result, ValidatorResult.FAILED)
        self.assertEqual(duplicate.sanitized_failure_category, "duplicate_reason")
        self.assertFalse(unexpected.provider_success)
        self.assertFalse(unexpected.candidate_returned)
        self.assertEqual(unexpected.sanitized_failure_category, "unexpected")
        self.assertNotIn("raw secret", unexpected.model_dump_json())

    async def test_missing_acknowledgement_prevents_client_and_files(self) -> None:
        client_factory = Mock()
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = EvalArtifactPaths(
                observations=Path(temporary_directory) / "observations.jsonl",
                report=Path(temporary_directory) / "report.json",
            )
            with self.assertRaises(PaidCallAcknowledgementError):
                await execute_eval(
                    real_settings(),
                    self.small_development,
                    samples_per_case=1,
                    inter_request_delay_seconds=0,
                    acknowledge_paid_calls=False,
                    fake_dry_run=False,
                    debug_holdout_details=False,
                    paths=paths,
                    client_factory=client_factory,
                )
            self.assertFalse(paths.observations.exists())
            self.assertFalse(paths.report.exists())

        client_factory.assert_not_called()

    async def test_provider_failure_report_exists_before_threshold_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = EvalArtifactPaths(
                observations=Path(temporary_directory) / "observations.jsonl",
                report=Path(temporary_directory) / "report.json",
            )
            result = await execute_eval(
                real_settings(),
                self.small_development,
                samples_per_case=1,
                inter_request_delay_seconds=0,
                acknowledge_paid_calls=True,
                fake_dry_run=False,
                debug_holdout_details=False,
                paths=paths,
                client_factory=lambda _settings: AlwaysRateLimitedOpenAIClient(),
            )

            self.assertTrue(paths.report.exists())
            stored_report = json.loads(paths.report.read_text(encoding="utf-8"))
            self.assertFalse(stored_report["thresholds"]["release_passed"])
            self.assertEqual(eval_exit_code(result), 1)

    async def test_normal_holdout_artifact_hides_case_claims(self) -> None:
        holdout = await build_holdout_dataset()
        one_case_holdout = ExplanationEvalDataset(
            dataset_id=holdout.dataset_id,
            dataset_version=holdout.dataset_version,
            split=holdout.split,
            cases=holdout.cases[:1],
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = EvalArtifactPaths(
                observations=Path(temporary_directory) / "observations.jsonl",
                report=Path(temporary_directory) / "report.json",
            )
            result = await execute_eval(
                fake_settings(),
                one_case_holdout,
                samples_per_case=1,
                inter_request_delay_seconds=0,
                acknowledge_paid_calls=False,
                fake_dry_run=True,
                debug_holdout_details=False,
                paths=paths,
            )
            stored_observation = json.loads(
                paths.observations.read_text(encoding="utf-8").strip()
            )

        self.assertTrue(DETAIL_FIELDS.isdisjoint(stored_observation))
        self.assertEqual(result.report.development_case_reliability, ())

    async def test_debug_holdout_artifact_explicitly_includes_details(self) -> None:
        holdout = await build_holdout_dataset()
        one_case_holdout = ExplanationEvalDataset(
            dataset_id=holdout.dataset_id,
            dataset_version=holdout.dataset_version,
            split=holdout.split,
            cases=holdout.cases[:1],
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = EvalArtifactPaths(
                observations=Path(temporary_directory) / "observations.jsonl",
                report=Path(temporary_directory) / "report.json",
            )
            await execute_eval(
                fake_settings(),
                one_case_holdout,
                samples_per_case=1,
                inter_request_delay_seconds=0,
                acknowledge_paid_calls=False,
                fake_dry_run=True,
                debug_holdout_details=True,
                paths=paths,
            )
            stored_observation = json.loads(
                paths.observations.read_text(encoding="utf-8").strip()
            )

        self.assertTrue(DETAIL_FIELDS.issubset(stored_observation))

    async def test_reports_are_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = EvalArtifactPaths(
                observations=Path(temporary_directory) / "observations.jsonl",
                report=Path(temporary_directory) / "report.json",
            )
            await execute_eval(
                fake_settings(),
                self.small_development,
                samples_per_case=1,
                inter_request_delay_seconds=0,
                acknowledge_paid_calls=False,
                fake_dry_run=True,
                debug_holdout_details=False,
                paths=paths,
            )
            artifact_text = (
                paths.observations.read_text(encoding="utf-8")
                + paths.report.read_text(encoding="utf-8")
            ).lower()

        for forbidden in (
            "test-secret",
            "authorization",
            "deterministic fake prose",
            "repository_owner",
            "linked_jira_key",
            "acme",
            "eng-",
        ):
            self.assertNotIn(forbidden, artifact_text)

    async def test_completed_run_can_save_and_compare_a_compatible_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            baseline_path = root / "baseline.json"
            first_paths = EvalArtifactPaths(
                observations=root / "first.observations.jsonl",
                report=root / "first.report.json",
            )
            await execute_eval(
                fake_settings(),
                self.small_development,
                samples_per_case=1,
                inter_request_delay_seconds=0,
                acknowledge_paid_calls=False,
                fake_dry_run=True,
                debug_holdout_details=False,
                paths=first_paths,
                save_baseline_path=baseline_path,
            )
            second_paths = EvalArtifactPaths(
                observations=root / "second.observations.jsonl",
                report=root / "second.report.json",
            )
            compared = await execute_eval(
                fake_settings(),
                self.small_development,
                samples_per_case=1,
                inter_request_delay_seconds=0,
                acknowledge_paid_calls=False,
                fake_dry_run=True,
                debug_holdout_details=False,
                paths=second_paths,
                baseline_path=baseline_path,
            )

            stored_report = json.loads(
                second_paths.report.read_text(encoding="utf-8")
            )

        self.assertIsNotNone(compared.baseline_comparison)
        self.assertTrue(compared.baseline_comparison.compatible)
        self.assertTrue(stored_report["baseline_comparison"]["compatible"])
        self.assertEqual(
            compared.baseline_comparison.metric_deltas[
                "candidate_end_to_end_quality_rate"
            ],
            0,
        )

    async def test_preflight_reports_exact_counts_without_client_construction(self) -> None:
        arguments = argparse.Namespace(
            dataset=EvalDatasetSplit.DEVELOPMENT.value,
            samples_per_case=2,
            inter_request_delay_seconds=0.5,
            preflight=True,
            acknowledge_paid_calls=False,
            fake_dry_run=False,
            debug_holdout_details=False,
            baseline=None,
            save_baseline=None,
        )
        output: list[str] = []
        client_factory = Mock()
        with (
            patch.object(LLMSettings, "from_environment", return_value=fake_settings()),
            patch("app.evals.runner.create_llm_client", client_factory),
            patch("builtins.print", side_effect=lambda value: output.append(str(value))),
        ):
            exit_code = await _run_cli(arguments)

        self.assertEqual(exit_code, 0)
        self.assertIn("case_count=11", output)
        self.assertIn("samples_per_case=2", output)
        self.assertIn("planned_request_count=22", output)
        self.assertIn("maximum_output_tokens_if_run=11264", output)
        self.assertIn("external_calls=0", output)
        client_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
