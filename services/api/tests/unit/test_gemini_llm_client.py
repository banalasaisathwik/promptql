import unittest
import json
from types import SimpleNamespace

import httpx
from openai import AuthenticationError, BadRequestError

from app.connectors.fakes import FakeGitHubConnector, FakeJiraConnector
from app.connectors.fixture_catalog import FAILED_CI_REQUEST
from app.explanations import (
    ExplanationErrorCode,
    GeneratedExplanation,
    GeminiLLMClient,
    LLMProviderError,
    LLMProviderFailureCategory,
    MergeReadinessExplanationService,
    MergeReadinessExplanationError,
    build_explanation_input,
)
from app.explanations.gemini_client import GeminiStructuredClaims
from app.policy import MergeReadinessDecision, evaluate_merge_readiness
from app.observability.contracts import LLM_TOKEN_USAGE_METRIC
from tests.telemetry_support import create_telemetry_harness


async def _blocked_policy_result():
    github = await FakeGitHubConnector().get_pull_request(FAILED_CI_REQUEST)
    jira = await FakeJiraConnector().get_issue(github.linked_jira_key)
    return evaluate_merge_readiness(github, jira)


def _generated_for(explanation_input):
    return GeneratedExplanation(
        decision=explanation_input.decision,
        summary="Gemini prose that the service must discard.",
        reason_codes=tuple(
            dict.fromkeys(explanation_input.blocker_reason_codes)
        ),
        action_codes=tuple(
            dict.fromkeys(explanation_input.pending_action_codes)
        ),
    )


def _claims_for(explanation_input):
    generated = _generated_for(explanation_input)
    return GeminiStructuredClaims(
        decision=generated.decision.value,
        summary=generated.summary,
        reason_indexes=list(range(len(generated.reason_codes))),
        action_indexes=list(range(len(generated.action_codes))),
    )


class RecordingChatCompletions:
    def __init__(self, response=None, error=None) -> None:
        self.response = response
        self.error = error
        self.requests = []

    async def parse(self, **request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


class RecordingGeminiSDKClient:
    def __init__(self, completions) -> None:
        self.beta = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _adapter(completions):
    return GeminiLLMClient(
        client=RecordingGeminiSDKClient(completions),
        model="gemini-2.5-flash",
        request_timeout_seconds=23,
        max_output_tokens=444,
    )


class GeminiLLMClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_uses_chat_structured_output_and_maps_usage(self) -> None:
        policy_result = await _blocked_policy_result()
        explanation_input = build_explanation_input(policy_result)
        generated = _generated_for(explanation_input)
        response = SimpleNamespace(
            choices=(
                SimpleNamespace(
                    message=SimpleNamespace(
                        parsed=_claims_for(explanation_input),
                        refusal=None,
                    )
                ),
            ),
            usage=SimpleNamespace(
                prompt_tokens=31,
                completion_tokens=11,
                total_tokens=42,
            ),
        )
        completions = RecordingChatCompletions(response=response)

        structured = await _adapter(completions).generate_structured(
            explanation_input
        )

        self.assertEqual(
            GeneratedExplanation.model_validate(structured.output),
            generated,
        )
        self.assertEqual(structured.token_usage.total_tokens, 42)
        request = completions.requests[0]
        self.assertEqual(request["model"], "gemini-2.5-flash")
        self.assertEqual(request["timeout"], 23)
        self.assertEqual(request["max_tokens"], 444)
        self.assertIs(request["response_format"], GeminiStructuredClaims)
        self.assertEqual(request["messages"][1]["role"], "user")
        provider_input = json.loads(request["messages"][1]["content"])
        self.assertEqual(provider_input["decision"], "blocked")
        self.assertEqual(
            provider_input["required_reason_codes"],
            [code.value for code in generated.reason_codes],
        )
        self.assertEqual(
            provider_input["pending_action_codes"],
            [code.value for code in generated.action_codes],
        )

    def test_provider_schema_avoids_google_serving_state_constraints(self) -> None:
        schema_text = json.dumps(GeminiStructuredClaims.model_json_schema())

        self.assertNotIn('"enum"', schema_text)
        self.assertNotIn('"maxItems"', schema_text)
        self.assertNotIn('"maxLength"', schema_text)

    async def test_output_uses_existing_validator_and_discards_prose(self) -> None:
        policy_result = await _blocked_policy_result()
        explanation_input = build_explanation_input(policy_result)
        response = SimpleNamespace(
            choices=(
                SimpleNamespace(
                    message=SimpleNamespace(
                        parsed=_claims_for(explanation_input),
                        refusal=None,
                    )
                ),
            ),
            usage=None,
        )

        explanation = await MergeReadinessExplanationService(
            _adapter(RecordingChatCompletions(response=response))
        ).explain(policy_result)

        self.assertEqual(explanation.decision, MergeReadinessDecision.BLOCKED)
        self.assertNotIn("Gemini prose", explanation.model_dump_json())

    async def test_telemetry_records_only_the_bounded_gemini_identity(self) -> None:
        policy_result = await _blocked_policy_result()
        explanation_input = build_explanation_input(policy_result)
        response = SimpleNamespace(
            choices=(
                SimpleNamespace(
                    message=SimpleNamespace(
                        parsed=_claims_for(explanation_input),
                        refusal=None,
                    )
                ),
            ),
            usage=SimpleNamespace(
                prompt_tokens=13,
                completion_tokens=5,
                total_tokens=18,
            ),
        )
        harness = create_telemetry_harness()
        try:
            await MergeReadinessExplanationService(
                _adapter(RecordingChatCompletions(response=response)),
                telemetry=harness.telemetry,
            ).explain(policy_result)

            span = harness.span_exporter.get_finished_spans()[0]
            self.assertEqual(span.attributes["promptql.llm.provider"], "gemini")
            token_points = harness.metric_points(LLM_TOKEN_USAGE_METRIC)
            self.assertTrue(token_points)
            self.assertTrue(
                all(
                    point.attributes["llm.provider"] == "gemini"
                    for point in token_points
                )
            )
        finally:
            harness.shutdown()

    async def test_authentication_failure_is_sanitized(self) -> None:
        request = httpx.Request(
            "POST",
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        )
        response = httpx.Response(401, request=request)
        provider_error = AuthenticationError(
            "raw-private-gemini-error",
            response=response,
            body={"secret": "must-not-escape"},
        )
        explanation_input = build_explanation_input(
            await _blocked_policy_result()
        )

        with self.assertRaises(LLMProviderError) as raised:
            await _adapter(
                RecordingChatCompletions(error=provider_error)
            ).generate_structured(explanation_input)

        self.assertEqual(
            raised.exception.category,
            LLMProviderFailureCategory.AUTHENTICATION,
        )
        self.assertNotIn("raw-private", str(raised.exception))
        self.assertNotIn("must-not-escape", str(raised.exception))

    async def test_invalid_provider_indexes_are_rejected_before_validation(
        self,
    ) -> None:
        explanation_input = build_explanation_input(
            await _blocked_policy_result()
        )
        response = SimpleNamespace(
            choices=(
                SimpleNamespace(
                    message=SimpleNamespace(
                        parsed=GeminiStructuredClaims(
                            decision=explanation_input.decision.value,
                            summary="Internal provider summary.",
                            reason_indexes=[999],
                            action_indexes=[],
                        ),
                        refusal=None,
                    )
                ),
            ),
            usage=None,
        )

        with self.assertRaises(LLMProviderError) as raised:
            await _adapter(
                RecordingChatCompletions(response=response)
            ).generate_structured(explanation_input)

        self.assertEqual(
            raised.exception.category,
            LLMProviderFailureCategory.INVALID_STRUCTURED_RESPONSE,
        )

    async def test_google_invalid_key_400_is_authentication_and_safely_logged(
        self,
    ) -> None:
        request = httpx.Request(
            "POST",
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        )
        response = httpx.Response(400, request=request)
        provider_error = BadRequestError(
            "raw-private-gemini-error",
            response=response,
            body=[
                {
                    "error": {
                        "code": 400,
                        "message": "Please pass a valid API key",
                        "status": "INVALID_ARGUMENT",
                    }
                }
            ],
        )
        policy_result = await _blocked_policy_result()
        harness = create_telemetry_harness()
        try:
            with self.assertRaises(MergeReadinessExplanationError) as raised:
                await MergeReadinessExplanationService(
                    _adapter(RecordingChatCompletions(error=provider_error)),
                    telemetry=harness.telemetry,
                ).explain(policy_result)

            self.assertEqual(
                raised.exception.code,
                ExplanationErrorCode.PROVIDER_FAILURE,
            )
            log_record = json.loads(harness.log_stream.getvalue())
            self.assertEqual(log_record["event"], "llm.explanation.failed")
            self.assertEqual(log_record["llm_provider"], "gemini")
            self.assertEqual(log_record["failure_category"], "authentication")
            observable_text = harness.log_stream.getvalue()
            self.assertNotIn("Please pass a valid API key", observable_text)
            self.assertNotIn("raw-private", observable_text)
        finally:
            harness.shutdown()

    async def test_refusal_and_missing_parsed_output_are_distinct(self) -> None:
        explanation_input = build_explanation_input(
            await _blocked_policy_result()
        )
        responses = (
            (
                SimpleNamespace(
                    choices=(
                        SimpleNamespace(
                            message=SimpleNamespace(
                                parsed=None,
                                refusal="provider refusal",
                            )
                        ),
                    ),
                    usage=None,
                ),
                LLMProviderFailureCategory.REFUSAL,
            ),
            (
                SimpleNamespace(choices=(), usage=None),
                LLMProviderFailureCategory.INVALID_STRUCTURED_RESPONSE,
            ),
        )

        for response, expected_category in responses:
            with self.subTest(category=expected_category):
                with self.assertRaises(LLMProviderError) as raised:
                    await _adapter(
                        RecordingChatCompletions(response=response)
                    ).generate_structured(explanation_input)
                self.assertEqual(raised.exception.category, expected_category)


if __name__ == "__main__":
    unittest.main()
