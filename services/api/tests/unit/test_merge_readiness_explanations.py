import unittest

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
    FakeLLMClient,
    LLMStructuredResponse,
    MergeReadinessExplanationError,
    MergeReadinessExplanationService,
    StrictExplanationValidationError,
    StrictMergeReadinessExplanationValidator,
    build_explanation_input,
    build_strict_explanation,
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


class RecordingLLMClient:
    def __init__(self, response: LLMStructuredResponse | None = None) -> None:
        self.response = response
        self.inputs = []

    async def generate_structured(self, explanation_input):
        self.inputs.append(explanation_input)
        if self.response is not None:
            return self.response
        explanation = build_strict_explanation(explanation_input)
        return LLMStructuredResponse(
            output=explanation.model_dump(mode="json")
        )


class FailingLLMClient:
    async def generate_structured(self, _explanation_input):
        raise RuntimeError("private-provider-token=must-not-escape")


class MergeReadinessExplanationTests(unittest.IsolatedAsyncioTestCase):
    def test_strict_templates_cover_every_policy_enum_value(self) -> None:
        self.assertEqual(set(SUMMARY_BY_DECISION), set(MergeReadinessDecision))
        self.assertEqual(set(REASON_TEXT_BY_CODE), set(PolicyReasonCode))
        self.assertEqual(set(ACTION_TEXT_BY_CODE), set(PendingActionCode))

    async def test_ready_blocked_and_unknown_results_are_explained(self) -> None:
        service = MergeReadinessExplanationService(FakeLLMClient())
        policy_results = (
            await _policy_result(),
            await _policy_result(FAILED_CI_REQUEST),
            await _unknown_policy_result(),
        )

        for policy_result in policy_results:
            with self.subTest(decision=policy_result.decision):
                original_values = policy_result.model_dump()
                explanation = await service.explain(policy_result)

                self.assertEqual(explanation.decision, policy_result.decision)
                self.assertTrue(explanation.summary)
                self.assertTrue(explanation.reasons)
                self.assertEqual(policy_result.model_dump(), original_values)

    async def test_client_receives_only_approved_sanitized_fields(self) -> None:
        secret = "github-token-and-private-provider-payload"
        policy_result = await _policy_result(FAILED_CI_REQUEST)
        values = policy_result.model_dump()
        values["blockers"][0]["message"] = secret
        values["evidence_references"][0]["value"] = secret
        policy_result_with_secret_evidence = type(policy_result).model_validate(values)
        client = RecordingLLMClient()

        await MergeReadinessExplanationService(client).explain(
            policy_result_with_secret_evidence
        )

        self.assertEqual(len(client.inputs), 1)
        sent_input = client.inputs[0]
        self.assertEqual(
            set(sent_input.model_dump()),
            {
                "decision",
                "primary_reason_code",
                "blocker_reason_codes",
                "missing_information_reason_codes",
                "pending_action_codes",
            },
        )
        self.assertNotIn(secret, sent_input.model_dump_json())

    async def test_invalid_output_is_a_typed_sanitized_error(self) -> None:
        private_output = "private-model-output-must-not-escape"
        client = RecordingLLMClient(
            LLMStructuredResponse(
                output={
                    "decision": "unsupported-decision",
                    "summary": private_output,
                    "reasons": (),
                    "recommended_actions": (),
                }
            )
        )

        with self.assertRaises(MergeReadinessExplanationError) as raised:
            await MergeReadinessExplanationService(client).explain(
                await _policy_result()
            )

        self.assertEqual(
            raised.exception.code,
            ExplanationErrorCode.INVALID_OUTPUT,
        )
        self.assertNotIn(private_output, str(raised.exception))
        self.assertNotIn("unsupported-decision", str(raised.exception))

    async def test_strict_validator_rejects_any_changed_content(self) -> None:
        policy_result = await _policy_result(FAILED_CI_REQUEST)
        explanation_input = build_explanation_input(policy_result)
        expected = build_strict_explanation(explanation_input)
        validator = StrictMergeReadinessExplanationValidator()

        changed_values = (
            {"summary": "Changed summary."},
            {"reasons": ()},
            {"reasons": (*expected.reasons, "An extra unsupported reason.")},
            {"recommended_actions": ()},
        )
        for changed in changed_values:
            with self.subTest(changed=changed):
                values = expected.model_dump()
                values.update(changed)
                altered = type(expected).model_validate(values)
                with self.assertRaises(StrictExplanationValidationError):
                    validator.validate(explanation_input, altered)

    async def test_strict_validator_preserves_reason_order(self) -> None:
        github = await FakeGitHubConnector().get_pull_request(FAILED_CI_REQUEST)
        values = github.model_dump()
        values["is_draft"] = True
        multi_blocker_github = GitHubPullRequest.model_validate(values)
        jira = await FakeJiraConnector().get_issue(github.linked_jira_key)
        policy_result = evaluate_merge_readiness(multi_blocker_github, jira)
        explanation_input = build_explanation_input(policy_result)
        expected = build_strict_explanation(explanation_input)
        reversed_values = expected.model_dump()
        reversed_values["reasons"] = tuple(reversed(expected.reasons))
        reordered = type(expected).model_validate(reversed_values)

        with self.assertRaises(StrictExplanationValidationError):
            StrictMergeReadinessExplanationValidator().validate(
                explanation_input,
                reordered,
            )

    async def test_mismatched_decision_is_rejected(self) -> None:
        client = RecordingLLMClient(
            LLMStructuredResponse(
                output={
                    "decision": MergeReadinessDecision.BLOCKED.value,
                    "summary": "Incorrectly changed decision.",
                    "reasons": (),
                    "recommended_actions": (),
                }
            )
        )

        with self.assertRaises(MergeReadinessExplanationError) as raised:
            await MergeReadinessExplanationService(client).explain(
                await _policy_result()
            )

        self.assertEqual(
            raised.exception.code,
            ExplanationErrorCode.VALIDATION_FAILED,
        )

    async def test_provider_failure_does_not_change_persisted_run(self) -> None:
        repository = InMemoryRunRepository()
        run = await MergeReadinessWorkflowService(
            FakeGitHubConnector(),
            FakeJiraConnector(),
            repository,
        ).execute(MERGE_READY_REQUEST)
        stored_before = repository.get(run.run_id)
        history_before = repository.history
        harness = create_telemetry_harness()
        try:
            with self.assertRaises(MergeReadinessExplanationError) as raised:
                await MergeReadinessExplanationService(
                    FailingLLMClient(),
                    telemetry=harness.telemetry,
                ).explain(run.result)

            self.assertEqual(
                raised.exception.code,
                ExplanationErrorCode.PROVIDER_FAILURE,
            )
            self.assertNotIn("private-provider-token", str(raised.exception))
            self.assertEqual(repository.get(run.run_id), stored_before)
            self.assertEqual(repository.history, history_before)

            span = harness.span_exporter.get_finished_spans()[0]
            self.assertEqual(
                span.attributes["promptql.llm.result"],
                "provider_failure",
            )
            self.assertEqual(
                span.attributes["error.type"],
                "llm_provider_failure",
            )
            duration_point = harness.metric_points(
                LLM_EXPLANATION_DURATION_METRIC
            )[0]
            self.assertEqual(
                dict(duration_point.attributes)["llm.result"],
                "provider_failure",
            )
            telemetry_text = repr(span.attributes) + harness.log_stream.getvalue()
            self.assertNotIn("private-provider-token", telemetry_text)
        finally:
            harness.shutdown()

    async def test_fake_client_is_deterministic(self) -> None:
        policy_result = await _policy_result(FAILED_CI_REQUEST)
        service = MergeReadinessExplanationService(FakeLLMClient())

        first = await service.explain(policy_result)
        second = await service.explain(policy_result)

        self.assertEqual(first, second)
        self.assertEqual(first.model_dump(), second.model_dump())

    async def test_telemetry_records_only_bounded_model_call_data(self) -> None:
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
            self.assertEqual(
                span.attributes["promptql.llm.result"],
                "success",
            )
            self.assertEqual(span.events, ())

            duration_points = harness.metric_points(
                LLM_EXPLANATION_DURATION_METRIC
            )
            token_points = harness.metric_points(LLM_TOKEN_USAGE_METRIC)
            self.assertEqual(len(duration_points), 1)
            self.assertEqual(len(token_points), 2)
            self.assertEqual(
                set(dict(duration_points[0].attributes)),
                {"llm.operation", "llm.result"},
            )
            self.assertTrue(
                all(
                    set(dict(point.attributes))
                    == {"llm.operation", "llm.token.type"}
                    for point in token_points
                )
            )

            telemetry_text = (
                repr(
                    tuple(
                        (span.name, dict(span.attributes), span.events)
                        for span in spans
                    )
                )
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
