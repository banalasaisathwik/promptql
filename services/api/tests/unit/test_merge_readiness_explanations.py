import unittest

from pydantic import ValidationError

from app.config import (
    GitHubConnectorMode,
    GitHubSettings,
    JiraConnectorMode,
    JiraSettings,
)
from app.connectors.fakes import FakeGitHubConnector, FakeJiraConnector
from app.connectors.fixture_catalog import FAILED_CI_REQUEST, MERGE_READY_REQUEST
from app.connectors.models import GitHubPullRequest, Mergeability
from app.explanations import (
    ExplanationErrorCode,
    ExplanationValidationError,
    ExplanationValidationFailureCode,
    FakeLLMClient,
    GeneratedExplanation,
    LLMStructuredResponse,
    MergeReadinessExplanationError,
    MergeReadinessExplanationService,
    StrictMergeReadinessExplanationValidator,
)
from app.explanations.templates import (
    ACTION_TEXT_BY_CODE,
    REASON_TEXT_BY_CODE,
    SUMMARY_BY_DECISION,
)
from app.main import create_app
from app.observability.contracts import (
    LLM_EXPLANATION_DURATION_METRIC,
    LLM_TOKEN_USAGE_METRIC,
)
from app.policy import (
    MergeReadinessDecision,
    PendingActionCode,
    PolicyReasonCode,
    evaluate_merge_readiness,
)
from app.runtime import InMemoryRunRepository
from app.workflows import MergeReadinessWorkflowService
from tests.telemetry_support import create_telemetry_harness


async def _policy_result(request=MERGE_READY_REQUEST):
    github = await FakeGitHubConnector().get_pull_request(request)
    jira = await FakeJiraConnector().get_issue(github.linked_jira_key)
    return evaluate_merge_readiness(github, jira)


async def _unknown_policy_result():
    github = await FakeGitHubConnector().get_pull_request(MERGE_READY_REQUEST)
    values = github.model_dump()
    values["mergeability"] = Mergeability.UNKNOWN
    unknown_github = GitHubPullRequest.model_validate(values)
    jira = await FakeJiraConnector().get_issue(github.linked_jira_key)
    return evaluate_merge_readiness(unknown_github, jira)


async def _multiple_blocker_policy_result():
    github = await FakeGitHubConnector().get_pull_request(FAILED_CI_REQUEST)
    values = github.model_dump()
    values["is_draft"] = True
    multiple_blocker_github = GitHubPullRequest.model_validate(values)
    jira = await FakeJiraConnector().get_issue(github.linked_jira_key)
    return evaluate_merge_readiness(multiple_blocker_github, jira)


def _generated_for(policy_result, summary="Untrusted generated prose."):
    reason_codes = tuple(
        dict.fromkeys(
            finding.reason_code
            for finding in (
                *policy_result.blockers,
                *policy_result.missing_information,
            )
        )
    )
    if not reason_codes:
        reason_codes = (policy_result.reason_code,)
    action_codes = tuple(
        dict.fromkeys(
            action.action_code for action in policy_result.pending_actions
        )
    )
    return GeneratedExplanation(
        decision=policy_result.decision,
        summary=summary,
        reason_codes=reason_codes,
        action_codes=action_codes,
    )


class RecordingLLMClient:
    def __init__(self, response=None) -> None:
        self.response = response
        self.inputs = []

    async def generate_structured(self, explanation_input):
        self.inputs.append(explanation_input)
        if self.response is not None:
            return self.response
        reason_codes = tuple(
            dict.fromkeys(
                (
                    *explanation_input.blocker_reason_codes,
                    *explanation_input.missing_information_reason_codes,
                )
            )
        )
        if not reason_codes:
            reason_codes = (explanation_input.primary_reason_code,)
        generated = GeneratedExplanation(
            decision=explanation_input.decision,
            summary="Recording client prose that must be discarded.",
            reason_codes=reason_codes,
            action_codes=tuple(
                dict.fromkeys(explanation_input.pending_action_codes)
            ),
        )
        return LLMStructuredResponse(
            output=generated.model_dump(mode="json")
        )


class FailingLLMClient:
    async def generate_structured(self, _explanation_input):
        raise RuntimeError("private-provider-token=must-not-escape")


class RecordingValidator(StrictMergeReadinessExplanationValidator):
    def __init__(self) -> None:
        self.call_count = 0

    def validate(self, policy_result, generated):
        self.call_count += 1
        return super().validate(policy_result, generated)


class MergeReadinessExplanationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.validator = StrictMergeReadinessExplanationValidator()

    def assert_validation_failure(
        self,
        policy_result,
        generated,
        expected_code: ExplanationValidationFailureCode,
    ) -> None:
        with self.assertRaises(ExplanationValidationError) as raised:
            self.validator.validate(policy_result, generated)
        self.assertEqual(raised.exception.code, expected_code)
        self.assertEqual(
            str(raised.exception),
            "The generated explanation failed validation.",
        )

    def test_templates_cover_every_policy_enum_value(self) -> None:
        self.assertEqual(set(SUMMARY_BY_DECISION), set(MergeReadinessDecision))
        self.assertEqual(set(REASON_TEXT_BY_CODE), set(PolicyReasonCode))
        self.assertEqual(set(ACTION_TEXT_BY_CODE), set(PendingActionCode))

    async def test_valid_ready_blocked_and_unknown_claims_pass(self) -> None:
        policy_results = (
            await _policy_result(),
            await _policy_result(FAILED_CI_REQUEST),
            await _unknown_policy_result(),
        )

        for policy_result in policy_results:
            with self.subTest(decision=policy_result.decision):
                generated = _generated_for(policy_result)
                first = self.validator.validate(policy_result, generated)
                second = self.validator.validate(policy_result, generated)

                self.assertEqual(first, second)
                self.assertEqual(first.decision, policy_result.decision)

    async def test_mismatched_decision_is_rejected(self) -> None:
        policy_result = await _policy_result()
        values = _generated_for(policy_result).model_dump()
        values["decision"] = MergeReadinessDecision.BLOCKED

        self.assert_validation_failure(
            policy_result,
            GeneratedExplanation.model_validate(values),
            ExplanationValidationFailureCode.DECISION_MISMATCH,
        )

    async def test_invented_reason_is_rejected(self) -> None:
        policy_result = await _policy_result(FAILED_CI_REQUEST)
        values = _generated_for(policy_result).model_dump()
        values["reason_codes"] = (
            *values["reason_codes"],
            PolicyReasonCode.MERGE_CONFLICT,
        )

        self.assert_validation_failure(
            policy_result,
            GeneratedExplanation.model_validate(values),
            ExplanationValidationFailureCode.UNSUPPORTED_REASON,
        )

    async def test_unsupported_action_is_rejected(self) -> None:
        policy_result = await _policy_result(FAILED_CI_REQUEST)
        values = _generated_for(policy_result).model_dump()
        values["action_codes"] = (
            *values["action_codes"],
            PendingActionCode.REOPEN_PR,
        )

        self.assert_validation_failure(
            policy_result,
            GeneratedExplanation.model_validate(values),
            ExplanationValidationFailureCode.UNSUPPORTED_ACTION,
        )

    async def test_missing_critical_blocker_is_rejected(self) -> None:
        policy_result = await _multiple_blocker_policy_result()
        values = _generated_for(policy_result).model_dump()
        values["reason_codes"] = values["reason_codes"][1:]

        self.assert_validation_failure(
            policy_result,
            GeneratedExplanation.model_validate(values),
            ExplanationValidationFailureCode.MISSING_REQUIRED_REASON,
        )

    async def test_missing_required_action_is_rejected(self) -> None:
        policy_result = await _policy_result(FAILED_CI_REQUEST)
        values = _generated_for(policy_result).model_dump()
        values["action_codes"] = ()

        self.assert_validation_failure(
            policy_result,
            GeneratedExplanation.model_validate(values),
            ExplanationValidationFailureCode.MISSING_REQUIRED_ACTION,
        )

    async def test_duplicate_reasons_and_actions_are_rejected(self) -> None:
        policy_result = await _policy_result(FAILED_CI_REQUEST)
        generated = _generated_for(policy_result)
        for field_name, expected_code in (
            ("reason_codes", ExplanationValidationFailureCode.DUPLICATE_REASON),
            ("action_codes", ExplanationValidationFailureCode.DUPLICATE_ACTION),
        ):
            with self.subTest(field=field_name):
                values = generated.model_dump()
                values[field_name] = (
                    *values[field_name],
                    values[field_name][0],
                )
                self.assert_validation_failure(
                    policy_result,
                    GeneratedExplanation.model_validate(values),
                    expected_code,
                )

    def test_empty_malformed_and_oversized_fields_fail_structure(self) -> None:
        valid = {
            "decision": "ready",
            "summary": "Generated summary.",
            "reason_codes": ("ready",),
            "action_codes": (),
        }
        invalid_values = (
            {**valid, "summary": ""},
            {**valid, "reason_codes": ()},
            {**valid, "decision": "unsupported"},
            {**valid, "reason_codes": ("invented",)},
            {**valid, "summary": "x" * 1_001},
            {**valid, "reason_codes": ("ready",) * 51},
        )

        for values in invalid_values:
            with self.subTest(values=values):
                with self.assertRaises(ValidationError):
                    GeneratedExplanation.model_validate(values)

    async def test_ready_cannot_claim_remediation(self) -> None:
        policy_result = await _policy_result()
        generated = GeneratedExplanation(
            decision=MergeReadinessDecision.READY,
            summary="Generated prose.",
            reason_codes=(PolicyReasonCode.READY,),
            action_codes=(PendingActionCode.FIX_CI_CHECK,),
        )

        self.assert_validation_failure(
            policy_result,
            generated,
            ExplanationValidationFailureCode.CONTRADICTORY_CLAIM,
        )

    async def test_blocked_cannot_claim_the_ready_reason(self) -> None:
        policy_result = await _policy_result(FAILED_CI_REQUEST)
        generated = GeneratedExplanation(
            decision=MergeReadinessDecision.BLOCKED,
            summary="Generated prose can say anything because it is discarded.",
            reason_codes=(PolicyReasonCode.READY,),
            action_codes=(PendingActionCode.FIX_CI_CHECK,),
        )

        self.assert_validation_failure(
            policy_result,
            generated,
            ExplanationValidationFailureCode.CONTRADICTORY_CLAIM,
        )

    async def test_unknown_requires_the_missing_evidence_reason(self) -> None:
        policy_result = await _unknown_policy_result()
        generated = GeneratedExplanation(
            decision=MergeReadinessDecision.UNKNOWN,
            summary="Generated prose.",
            reason_codes=(PolicyReasonCode.CI_CHECK_PENDING,),
            action_codes=(PendingActionCode.RETRY_EVIDENCE,),
        )

        self.assert_validation_failure(
            policy_result,
            generated,
            ExplanationValidationFailureCode.UNKNOWN_MISSING_EVIDENCE,
        )

    async def test_generated_prose_is_never_returned_or_telemetried(self) -> None:
        secret_prose = "private-model-output-must-never-escape"
        policy_result = await _policy_result(FAILED_CI_REQUEST)
        generated = _generated_for(policy_result, summary=secret_prose)
        client = RecordingLLMClient(
            LLMStructuredResponse(output=generated.model_dump(mode="json"))
        )
        harness = create_telemetry_harness()
        try:
            explanation = await MergeReadinessExplanationService(
                client,
                telemetry=harness.telemetry,
            ).explain(policy_result)

            self.assertNotIn(secret_prose, explanation.model_dump_json())
            self.assertEqual(
                explanation.summary,
                SUMMARY_BY_DECISION[MergeReadinessDecision.BLOCKED],
            )
            telemetry_text = (
                repr(harness.span_exporter.get_finished_spans()[0].attributes)
                + harness.log_stream.getvalue()
            )
            self.assertNotIn(secret_prose, telemetry_text)
        finally:
            harness.shutdown()

    async def test_malformed_generated_output_has_sanitized_category(self) -> None:
        private_output = "private-malformed-output"
        client = RecordingLLMClient(
            LLMStructuredResponse(
                output={
                    "decision": "unsupported",
                    "summary": private_output,
                    "reason_codes": (),
                    "action_codes": (),
                }
            )
        )
        harness = create_telemetry_harness()
        try:
            with self.assertRaises(MergeReadinessExplanationError) as raised:
                await MergeReadinessExplanationService(
                    client,
                    telemetry=harness.telemetry,
                ).explain(await _policy_result())

            self.assertEqual(
                raised.exception.code,
                ExplanationErrorCode.VALIDATION_FAILED,
            )
            self.assertNotIn(private_output, str(raised.exception))
            span = harness.span_exporter.get_finished_spans()[0]
            self.assertEqual(
                span.attributes[
                    "promptql.llm.validation.failure_category"
                ],
                "invalid_structure",
            )
            self.assertNotIn(private_output, repr(span.attributes))
        finally:
            harness.shutdown()

    async def test_semantic_failure_telemetry_uses_only_stable_category(self) -> None:
        private_output = "private unsupported explanation output"
        policy_result = await _policy_result(FAILED_CI_REQUEST)
        generated = _generated_for(policy_result, summary=private_output)
        values = generated.model_dump()
        values["reason_codes"] = (
            *values["reason_codes"],
            PolicyReasonCode.MERGE_CONFLICT,
        )
        client = RecordingLLMClient(
            LLMStructuredResponse(output=values)
        )
        harness = create_telemetry_harness()
        try:
            with self.assertRaises(MergeReadinessExplanationError):
                await MergeReadinessExplanationService(
                    client,
                    telemetry=harness.telemetry,
                ).explain(policy_result)

            span = harness.span_exporter.get_finished_spans()[0]
            self.assertEqual(
                span.attributes["promptql.llm.validation.result"],
                "failure",
            )
            self.assertEqual(
                span.attributes[
                    "promptql.llm.validation.failure_category"
                ],
                "unsupported_reason",
            )
            telemetry_text = repr(span.attributes) + harness.log_stream.getvalue()
            self.assertNotIn(private_output, telemetry_text)
            self.assertNotIn("merge_conflict", telemetry_text)
        finally:
            harness.shutdown()

    async def test_envelope_failure_remains_invalid_output(self) -> None:
        client = RecordingLLMClient({"unexpected": "private-envelope"})

        with self.assertRaises(MergeReadinessExplanationError) as raised:
            await MergeReadinessExplanationService(client).explain(
                await _policy_result()
            )

        self.assertEqual(raised.exception.code, ExplanationErrorCode.INVALID_OUTPUT)
        self.assertNotIn("private-envelope", str(raised.exception))

    async def test_fake_output_passes_through_the_real_validator(self) -> None:
        validator = RecordingValidator()
        explanation = await MergeReadinessExplanationService(
            FakeLLMClient(),
            validator=validator,
        ).explain(await _policy_result(FAILED_CI_REQUEST))

        self.assertEqual(validator.call_count, 1)
        self.assertEqual(explanation.decision, MergeReadinessDecision.BLOCKED)

    async def test_repeated_policy_categories_render_once(self) -> None:
        github = await FakeGitHubConnector().get_pull_request(FAILED_CI_REQUEST)
        values = github.model_dump()
        values["required_checks"] = (
            *values["required_checks"],
            {"name": "integration-tests", "status": "failed"},
        )
        repeated_category_github = GitHubPullRequest.model_validate(values)
        jira = await FakeJiraConnector().get_issue(github.linked_jira_key)
        policy_result = evaluate_merge_readiness(
            repeated_category_github,
            jira,
        )

        explanation = await MergeReadinessExplanationService(
            FakeLLMClient()
        ).explain(policy_result)

        failed_check_blockers = tuple(
            blocker
            for blocker in policy_result.blockers
            if blocker.reason_code is PolicyReasonCode.CI_CHECK_FAILED
        )
        self.assertEqual(len(failed_check_blockers), 2)
        self.assertEqual(
            explanation.reasons,
            (REASON_TEXT_BY_CODE[PolicyReasonCode.CI_CHECK_FAILED],),
        )

    async def test_provider_and_validation_failures_do_not_mutate_policy(self) -> None:
        repository = InMemoryRunRepository()
        run = await MergeReadinessWorkflowService(
            FakeGitHubConnector(),
            FakeJiraConnector(),
            repository,
        ).execute(MERGE_READY_REQUEST)
        policy_result = run.result
        original = policy_result.model_dump()
        stored_before = repository.get(run.run_id)
        history_before = repository.history
        mismatched = GeneratedExplanation(
            decision=MergeReadinessDecision.BLOCKED,
            summary="secret contradictory output",
            reason_codes=(PolicyReasonCode.READY,),
            action_codes=(),
        )
        clients = (
            FailingLLMClient(),
            RecordingLLMClient(
                LLMStructuredResponse(
                    output=mismatched.model_dump(mode="json")
                )
            ),
        )

        for client in clients:
            with self.subTest(client=type(client).__name__):
                with self.assertRaises(MergeReadinessExplanationError):
                    await MergeReadinessExplanationService(client).explain(
                        policy_result
                    )
                self.assertEqual(policy_result.model_dump(), original)
                self.assertEqual(repository.get(run.run_id), stored_before)
                self.assertEqual(repository.history, history_before)

    async def test_validation_success_uses_bounded_telemetry(self) -> None:
        harness = create_telemetry_harness()
        try:
            explanation = await MergeReadinessExplanationService(
                FakeLLMClient(),
                telemetry=harness.telemetry,
            ).explain(await _policy_result())

            spans = harness.span_exporter.get_finished_spans()
            self.assertEqual(len(spans), 1)
            span = spans[0]
            self.assertEqual(span.name, "merge_readiness.explanation.generate")
            self.assertEqual(span.attributes["promptql.llm.result"], "success")
            self.assertEqual(
                span.attributes["promptql.llm.validation.result"],
                "success",
            )
            self.assertNotIn(
                "promptql.llm.validation.failure_category",
                span.attributes,
            )

            duration_points = harness.metric_points(
                LLM_EXPLANATION_DURATION_METRIC
            )
            token_points = harness.metric_points(LLM_TOKEN_USAGE_METRIC)
            self.assertEqual(len(duration_points), 1)
            self.assertEqual(len(token_points), 2)
            telemetry_text = (
                repr(span.attributes)
                + repr(
                    tuple(
                        dict(point.attributes)
                        for point in duration_points + token_points
                    )
                )
                + harness.log_stream.getvalue()
            )
            self.assertNotIn(explanation.summary, telemetry_text)
            self.assertNotIn(explanation.reasons[0], telemetry_text)
        finally:
            harness.shutdown()

    async def test_application_boundary_uses_injected_client(self) -> None:
        client = RecordingLLMClient()
        application = create_app(
            github_settings=GitHubSettings(
                mode=GitHubConnectorMode.FAKE,
                token=None,
                api_base_url="https://api.github.com",
                request_timeout_seconds=10,
            ),
            jira_settings=JiraSettings(
                mode=JiraConnectorMode.FAKE,
                base_url=None,
                email=None,
                api_token=None,
            ),
            llm_client=client,
        )

        explanation = await (
            application.state.merge_readiness_explanation_service.explain(
                await _policy_result()
            )
        )

        self.assertEqual(explanation.decision, MergeReadinessDecision.READY)
        self.assertEqual(len(client.inputs), 1)


if __name__ == "__main__":
    unittest.main()
