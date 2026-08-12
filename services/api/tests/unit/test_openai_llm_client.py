import unittest
from types import SimpleNamespace

import httpx
from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    PermissionDeniedError,
    RateLimitError,
)

from app.connectors.fakes import FakeGitHubConnector, FakeJiraConnector
from app.connectors.fixture_catalog import FAILED_CI_REQUEST
from app.explanations import (
    ExplanationErrorCode,
    GeneratedExplanation,
    LLMProviderError,
    LLMProviderFailureCategory,
    MergeReadinessExplanationError,
    MergeReadinessExplanationService,
    OpenAILLMClient,
    build_explanation_input,
)
from app.policy import MergeReadinessDecision, evaluate_merge_readiness
from app.observability.contracts import (
    LLM_EXPLANATION_DURATION_METRIC,
    LLM_TOKEN_USAGE_METRIC,
    LLMCallResult,
)
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
        summary="Provider prose that the service must discard.",
        reason_codes=reason_codes,
        action_codes=tuple(
            dict.fromkeys(explanation_input.pending_action_codes)
        ),
    )


class RecordingResponsesAPI:
    def __init__(self, response=None, error=None) -> None:
        self.response = response
        self.error = error
        self.requests = []

    async def parse(self, **request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


class RecordingOpenAISDKClient:
    def __init__(self, responses) -> None:
        self.responses = responses
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _adapter(responses):
    return OpenAILLMClient(
        client=RecordingOpenAISDKClient(responses),
        model="configured-model",
        request_timeout_seconds=19,
        max_output_tokens=333,
    )


def _status_error(error_type, status_code):
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(status_code, request=request)
    return error_type(
        "raw-private-provider-error",
        response=response,
        body={"secret": "must-not-escape"},
    )


class OpenAILLMClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_uses_structured_output_and_safe_request_options(self) -> None:
        policy_result = await _blocked_policy_result()
        explanation_input = build_explanation_input(policy_result)
        generated = _generated_for(explanation_input)
        response = SimpleNamespace(
            output_parsed=generated,
            output=(),
            usage=SimpleNamespace(
                input_tokens=41,
                output_tokens=12,
                total_tokens=53,
            ),
        )
        responses = RecordingResponsesAPI(response=response)

        structured = await _adapter(responses).generate_structured(
            explanation_input
        )

        self.assertEqual(
            GeneratedExplanation.model_validate(structured.output),
            generated,
        )
        self.assertEqual(structured.token_usage.total_tokens, 53)
        request = responses.requests[0]
        self.assertEqual(request["model"], "configured-model")
        self.assertEqual(request["timeout"], 19)
        self.assertEqual(request["max_output_tokens"], 333)
        self.assertIs(request["store"], False)
        self.assertIs(request["text_format"], GeneratedExplanation)
        self.assertEqual(
            request["input"],
            explanation_input.model_dump_json(),
        )
        self.assertNotIn("tools", request)
        self.assertNotIn("previous_response_id", request)

    async def test_adapter_output_passes_through_existing_validator(self) -> None:
        policy_result = await _blocked_policy_result()
        explanation_input = build_explanation_input(policy_result)
        response = SimpleNamespace(
            output_parsed=_generated_for(explanation_input),
            output=(),
            usage=None,
        )

        explanation = await MergeReadinessExplanationService(
            _adapter(RecordingResponsesAPI(response=response))
        ).explain(policy_result)

        self.assertEqual(explanation.decision, MergeReadinessDecision.BLOCKED)
        self.assertNotIn("Provider prose", explanation.model_dump_json())

    async def test_validator_rejects_decision_mismatch_and_missing_codes(self) -> None:
        policy_result = await _blocked_policy_result()
        explanation_input = build_explanation_input(policy_result)
        valid = _generated_for(explanation_input)
        invalid_outputs = (
            valid.model_copy(update={"decision": MergeReadinessDecision.READY}),
            valid.model_copy(update={"reason_codes": ()}),
        )

        for output in invalid_outputs:
            with self.subTest(output=output.model_dump(mode="json")):
                response = SimpleNamespace(
                    output_parsed=output,
                    output=(),
                    usage=None,
                )
                with self.assertRaises(MergeReadinessExplanationError) as raised:
                    await MergeReadinessExplanationService(
                        _adapter(RecordingResponsesAPI(response=response))
                    ).explain(policy_result)
                self.assertEqual(
                    raised.exception.code,
                    ExplanationErrorCode.VALIDATION_FAILED,
                )

    async def test_provider_exception_categories_are_sanitized(self) -> None:
        request = httpx.Request(
            "POST",
            "https://api.openai.com/v1/responses",
        )
        response = httpx.Response(200, request=request)
        failures = (
            (
                _status_error(AuthenticationError, 401),
                LLMProviderFailureCategory.AUTHENTICATION,
            ),
            (
                _status_error(PermissionDeniedError, 403),
                LLMProviderFailureCategory.PERMISSION,
            ),
            (
                _status_error(RateLimitError, 429),
                LLMProviderFailureCategory.RATE_LIMIT,
            ),
            (
                APITimeoutError(request),
                LLMProviderFailureCategory.TIMEOUT,
            ),
            (
                APIConnectionError(
                    message="raw-private-connection-error",
                    request=request,
                ),
                LLMProviderFailureCategory.CONNECTION,
            ),
            (
                _status_error(BadRequestError, 400),
                LLMProviderFailureCategory.INVALID_REQUEST,
            ),
            (
                APIResponseValidationError(
                    response=response,
                    body={"secret": "must-not-escape"},
                    message="raw-private-validation-error",
                ),
                LLMProviderFailureCategory.INVALID_STRUCTURED_RESPONSE,
            ),
            (
                _status_error(InternalServerError, 500),
                LLMProviderFailureCategory.UPSTREAM_UNAVAILABLE,
            ),
        )
        explanation_input = build_explanation_input(
            await _blocked_policy_result()
        )

        for provider_error, expected_category in failures:
            with self.subTest(category=expected_category):
                client = _adapter(RecordingResponsesAPI(error=provider_error))
                with self.assertRaises(LLMProviderError) as raised:
                    await client.generate_structured(explanation_input)
                self.assertEqual(raised.exception.category, expected_category)
                error_text = str(raised.exception)
                self.assertNotIn("raw-private", error_text)
                self.assertNotIn("must-not-escape", error_text)

    async def test_refusal_and_missing_parsed_output_are_distinct(self) -> None:
        refusal = SimpleNamespace(
            output_parsed=None,
            output=(
                SimpleNamespace(
                    content=(SimpleNamespace(type="refusal"),)
                ),
            ),
            usage=None,
        )
        invalid = SimpleNamespace(
            output_parsed=None,
            output=(),
            usage=None,
        )
        explanation_input = build_explanation_input(
            await _blocked_policy_result()
        )

        for response, expected_category in (
            (refusal, LLMProviderFailureCategory.REFUSAL),
            (
                invalid,
                LLMProviderFailureCategory.INVALID_STRUCTURED_RESPONSE,
            ),
        ):
            with self.subTest(category=expected_category):
                with self.assertRaises(LLMProviderError) as raised:
                    await _adapter(
                        RecordingResponsesAPI(response=response)
                    ).generate_structured(explanation_input)
                self.assertEqual(raised.exception.category, expected_category)

    async def test_provider_failure_preserves_policy_and_safe_telemetry(self) -> None:
        policy_result = await _blocked_policy_result()
        original_policy = policy_result.model_dump()
        request = httpx.Request(
            "POST",
            "https://api.openai.com/v1/responses",
        )
        harness = create_telemetry_harness()
        try:
            client = _adapter(
                RecordingResponsesAPI(
                    error=APIConnectionError(
                        message="raw-secret-provider-message",
                        request=request,
                    )
                )
            )
            with self.assertRaises(MergeReadinessExplanationError) as raised:
                await MergeReadinessExplanationService(
                    client,
                    telemetry=harness.telemetry,
                ).explain(policy_result)

            self.assertEqual(
                raised.exception.code,
                ExplanationErrorCode.PROVIDER_FAILURE,
            )
            self.assertEqual(policy_result.model_dump(), original_policy)
            span = harness.span_exporter.get_finished_spans()[0]
            self.assertEqual(span.attributes["promptql.llm.provider"], "openai")
            self.assertEqual(
                span.attributes["promptql.llm.prompt.id"],
                "merge-readiness-explanation",
            )
            self.assertEqual(span.attributes["promptql.llm.prompt.version"], "v1")
            self.assertEqual(
                span.attributes["promptql.llm.model.fingerprint"],
                "4bbcf8b89b51d285",
            )
            self.assertEqual(
                span.attributes["promptql.llm.failure.category"],
                "connection",
            )
            observable_text = repr(span.attributes) + harness.log_stream.getvalue()
            self.assertNotIn("raw-secret-provider-message", observable_text)
        finally:
            harness.shutdown()

    async def test_token_telemetry_excludes_prompt_and_generated_content(self) -> None:
        policy_result = await _blocked_policy_result()
        explanation_input = build_explanation_input(policy_result)
        private_output = "private-generated-output-must-not-escape"
        generated = _generated_for(explanation_input).model_copy(
            update={"summary": private_output}
        )
        response = SimpleNamespace(
            output_parsed=generated,
            output=(),
            usage=SimpleNamespace(
                input_tokens=21,
                output_tokens=8,
                total_tokens=29,
            ),
        )
        harness = create_telemetry_harness()
        try:
            explanation = await MergeReadinessExplanationService(
                _adapter(RecordingResponsesAPI(response=response)),
                telemetry=harness.telemetry,
            ).explain(policy_result)

            points = harness.metric_points(LLM_TOKEN_USAGE_METRIC)
            counts = {
                point.attributes["llm.token.type"]: point.value
                for point in points
            }
            self.assertEqual(counts, {"input": 21, "output": 8, "total": 29})
            self.assertTrue(
                all(point.attributes["llm.provider"] == "openai" for point in points)
            )
            observable_text = (
                repr(harness.span_exporter.get_finished_spans()[0].attributes)
                + repr(tuple(dict(point.attributes) for point in points))
                + harness.log_stream.getvalue()
            )
            self.assertNotIn(private_output, explanation.model_dump_json())
            self.assertNotIn(private_output, observable_text)
            self.assertNotIn(explanation_input.model_dump_json(), observable_text)
        finally:
            harness.shutdown()

    async def test_unknown_provider_cannot_become_a_metric_label(self) -> None:
        private_provider = "user-controlled-provider-value"
        harness = create_telemetry_harness()
        try:
            harness.telemetry.record_llm_explanation(
                duration_ms=1,
                result=LLMCallResult.SUCCESS,
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
                provider=private_provider,
            )

            self.assertEqual(
                harness.metric_points(LLM_EXPLANATION_DURATION_METRIC),
                [],
            )
            self.assertEqual(harness.metric_points(LLM_TOKEN_USAGE_METRIC), [])
            self.assertNotIn(private_provider, harness.log_stream.getvalue())
        finally:
            harness.shutdown()


if __name__ == "__main__":
    unittest.main()
