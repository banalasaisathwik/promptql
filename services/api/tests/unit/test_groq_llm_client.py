import json
import unittest
from types import SimpleNamespace

import httpx
from openai import BadRequestError, LengthFinishReasonError, RateLimitError
from openai.types.chat import ChatCompletion

from app.connectors.fakes import FakeGitHubConnector, FakeJiraConnector
from app.connectors.fixture_catalog import FAILED_CI_REQUEST
from app.explanations import (
    ExplanationErrorCode,
    GeneratedExplanation,
    GroqLLMClient,
    LLMProviderError,
    LLMProviderErrorDetails,
    LLMProviderFailureCategory,
    MergeReadinessExplanationError,
    MergeReadinessExplanationService,
    OpenRouterLLMClient,
    TypedLLMRequest,
    build_explanation_input,
)
from app.observability.contracts import LLM_TOKEN_USAGE_METRIC
from app.policy import MergeReadinessDecision, evaluate_merge_readiness
from tests.telemetry_support import create_telemetry_harness


async def _blocked_policy_result():
    github = await FakeGitHubConnector().get_pull_request(FAILED_CI_REQUEST)
    jira = await FakeJiraConnector().get_issue(github.linked_jira_key)
    return evaluate_merge_readiness(github, jira)


def _generated_for(explanation_input):
    reason_codes = tuple(
        dict.fromkeys(
            (
                *explanation_input.blocker_reason_codes,
                *explanation_input.missing_information_reason_codes,
            )
        )
    ) or (explanation_input.primary_reason_code,)
    return GeneratedExplanation(
        decision=explanation_input.decision,
        summary="Groq prose that the service must discard.",
        reason_codes=reason_codes,
        action_codes=tuple(dict.fromkeys(explanation_input.pending_action_codes)),
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


class RecordingGroqSDKClient:
    def __init__(self, completions) -> None:
        self.beta = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _adapter(completions):
    return GroqLLMClient(
        client=RecordingGroqSDKClient(completions),
        model="openai/gpt-oss-20b",
        request_timeout_seconds=14,
        max_output_tokens=300,
    )


def _response(parsed_output, *, usage=None, refusal=None):
    return SimpleNamespace(
        choices=(
            SimpleNamespace(
                message=SimpleNamespace(
                    parsed=parsed_output,
                    refusal=refusal,
                )
            ),
        ),
        usage=usage,
    )


class GroqLLMClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_uses_strict_schema_type_and_normalizes_usage(self) -> None:
        policy_result = await _blocked_policy_result()
        explanation_input = build_explanation_input(policy_result)
        generated = _generated_for(explanation_input)
        completions = RecordingChatCompletions(
            response=_response(
                generated,
                usage=SimpleNamespace(
                    prompt_tokens=25,
                    completion_tokens=9,
                    total_tokens=34,
                ),
            )
        )

        structured = await _adapter(completions).generate_structured(
            explanation_input
        )

        self.assertEqual(
            GeneratedExplanation.model_validate(structured.output),
            generated,
        )
        self.assertEqual(structured.token_usage.input_tokens, 25)
        self.assertEqual(structured.token_usage.output_tokens, 9)
        self.assertEqual(structured.token_usage.total_tokens, 34)
        request = completions.requests[0]
        self.assertEqual(request["model"], "openai/gpt-oss-20b")
        self.assertEqual(request["timeout"], 14)
        self.assertEqual(request["max_tokens"], 300)
        self.assertIs(request["response_format"], GeneratedExplanation)
        self.assertEqual(request["messages"][1]["role"], "user")
        self.assertEqual(
            json.loads(request["messages"][1]["content"]),
            explanation_input.model_dump(mode="json"),
        )
        self.assertNotIn("tools", request)

    async def test_rate_limit_is_one_sanitized_provider_failure(self) -> None:
        request = httpx.Request(
            "POST",
            "https://api.groq.com/openai/v1/chat/completions",
        )
        response = httpx.Response(429, request=request)
        provider_error = RateLimitError(
            "raw-private-groq-error",
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
            LLMProviderFailureCategory.RATE_LIMIT,
        )
        self.assertNotIn("raw-private", str(raised.exception))
        self.assertNotIn("must-not-escape", str(raised.exception))

    async def test_typed_json_validation_failure_preserves_safe_details(self) -> None:
        request = httpx.Request(
            "POST",
            "https://api.groq.com/openai/v1/chat/completions",
        )
        response = httpx.Response(400, request=request)
        provider_error = BadRequestError(
            "raw-private-groq-error",
            response=response,
            body={
                "error": {
                    "type": "invalid_request_error",
                    "code": "json_validate_failed",
                    "message": "Failed to validate JSON.",
                    "failed_generation": "private generated plan content",
                }
            },
        )
        explanation_input = build_explanation_input(
            await _blocked_policy_result()
        )

        with self.assertRaises(LLMProviderError) as raised:
            await _adapter(
                RecordingChatCompletions(error=provider_error)
            ).generate_typed(
                TypedLLMRequest(
                    system_instructions="Return structured output.",
                    input=explanation_input,
                    output_model=GeneratedExplanation,
                )
            )

        self.assertEqual(
            raised.exception.category,
            LLMProviderFailureCategory.INVALID_REQUEST,
        )
        self.assertEqual(
            raised.exception.details,
            LLMProviderErrorDetails(
                http_status=400,
                provider_type="invalid_request_error",
                provider_code="json_validate_failed",
                provider_message="Groq rejected generated structured output.",
                failed_generation_present=True,
                failed_generation_length=len("private generated plan content"),
            ),
        )
        self.assertNotIn("raw-private", repr(raised.exception.details))
        self.assertNotIn("private generated", repr(raised.exception.details))

    async def test_typed_requests_use_low_reasoning(self) -> None:
        policy_result = await _blocked_policy_result()
        explanation_input = build_explanation_input(policy_result)
        completions = RecordingChatCompletions(
            response=_response(_generated_for(explanation_input))
        )

        await _adapter(completions).generate_typed(
            TypedLLMRequest(
                system_instructions="Return structured output.",
                input=explanation_input,
                output_model=GeneratedExplanation,
            )
        )

        self.assertEqual(completions.requests[0]["reasoning_effort"], "low")

    async def test_typed_length_finish_is_a_safe_structured_response_failure(self) -> None:
        completion = ChatCompletion.model_validate(
            {
                "id": "safe-test",
                "created": 0,
                "model": "openai/gpt-oss-120b",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "length",
                        "message": {"role": "assistant", "content": ""},
                    }
                ],
            }
        )
        error = LengthFinishReasonError(completion=completion)
        policy_result = await _blocked_policy_result()
        explanation_input = build_explanation_input(policy_result)

        with self.assertRaises(LLMProviderError) as raised:
            await _adapter(RecordingChatCompletions(error=error)).generate_typed(
                TypedLLMRequest(
                    system_instructions="Return structured output.",
                    input=explanation_input,
                    output_model=GeneratedExplanation,
                )
            )

        self.assertEqual(
            raised.exception.category,
            LLMProviderFailureCategory.INVALID_STRUCTURED_RESPONSE,
        )
        self.assertEqual(raised.exception.details.provider_code, "length_finish_reason")

    async def test_openrouter_typed_requests_omit_groq_only_reasoning(self) -> None:
        policy_result = await _blocked_policy_result()
        explanation_input = build_explanation_input(policy_result)
        completions = RecordingChatCompletions(
            response=_response(_generated_for(explanation_input))
        )
        adapter = OpenRouterLLMClient(
            client=RecordingGroqSDKClient(completions),
            model="openai/gpt-oss-120b",
            request_timeout_seconds=14,
            max_output_tokens=300,
        )

        await adapter.generate_typed(
            TypedLLMRequest(
                system_instructions="Return structured output.",
                input=explanation_input,
                output_model=GeneratedExplanation,
            )
        )

        self.assertNotIn("reasoning_effort", completions.requests[0])

    async def test_missing_or_malformed_parsed_output_is_rejected(self) -> None:
        explanation_input = build_explanation_input(
            await _blocked_policy_result()
        )
        malformed_responses = (
            SimpleNamespace(choices=(), usage=None),
            _response({"decision": "blocked"}),
        )

        for response in malformed_responses:
            with self.subTest(response=response):
                with self.assertRaises(LLMProviderError) as raised:
                    await _adapter(
                        RecordingChatCompletions(response=response)
                    ).generate_structured(explanation_input)
                self.assertEqual(
                    raised.exception.category,
                    LLMProviderFailureCategory.INVALID_STRUCTURED_RESPONSE,
                )

    async def test_refusal_is_distinct_from_malformed_output(self) -> None:
        explanation_input = build_explanation_input(
            await _blocked_policy_result()
        )

        with self.assertRaises(LLMProviderError) as raised:
            await _adapter(
                RecordingChatCompletions(
                    response=_response(None, refusal="provider refusal")
                )
            ).generate_structured(explanation_input)

        self.assertEqual(
            raised.exception.category,
            LLMProviderFailureCategory.REFUSAL,
        )

    async def test_schema_valid_unsupported_claims_reach_existing_validator(self) -> None:
        policy_result = await _blocked_policy_result()
        explanation_input = build_explanation_input(policy_result)
        unsupported = _generated_for(explanation_input).model_copy(
            update={"decision": MergeReadinessDecision.READY}
        )

        with self.assertRaises(MergeReadinessExplanationError) as raised:
            await MergeReadinessExplanationService(
                _adapter(
                    RecordingChatCompletions(
                        response=_response(unsupported)
                    )
                )
            ).explain(policy_result)

        self.assertEqual(
            raised.exception.code,
            ExplanationErrorCode.VALIDATION_FAILED,
        )

    async def test_telemetry_uses_groq_identity_and_safe_model_fingerprint(self) -> None:
        policy_result = await _blocked_policy_result()
        explanation_input = build_explanation_input(policy_result)
        generated = _generated_for(explanation_input)
        private_prose = generated.summary
        harness = create_telemetry_harness()
        try:
            explanation = await MergeReadinessExplanationService(
                _adapter(
                    RecordingChatCompletions(
                        response=_response(
                            generated,
                            usage=SimpleNamespace(
                                prompt_tokens=17,
                                completion_tokens=7,
                                total_tokens=24,
                            ),
                        )
                    )
                ),
                telemetry=harness.telemetry,
            ).explain(policy_result)

            span = harness.span_exporter.get_finished_spans()[0]
            self.assertEqual(span.attributes["promptql.llm.provider"], "groq")
            self.assertEqual(
                len(span.attributes["promptql.llm.model.fingerprint"]),
                16,
            )
            token_points = harness.metric_points(LLM_TOKEN_USAGE_METRIC)
            self.assertTrue(token_points)
            self.assertTrue(
                all(
                    point.attributes["llm.provider"] == "groq"
                    for point in token_points
                )
            )
            observable_text = (
                repr(span.attributes)
                + repr(tuple(dict(point.attributes) for point in token_points))
                + harness.log_stream.getvalue()
            )
            self.assertNotIn("openai/gpt-oss-20b", observable_text)
            self.assertNotIn(private_prose, explanation.model_dump_json())
            self.assertNotIn(private_prose, observable_text)
        finally:
            harness.shutdown()


if __name__ == "__main__":
    unittest.main()
