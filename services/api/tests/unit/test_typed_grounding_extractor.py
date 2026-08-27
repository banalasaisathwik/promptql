import unittest

from app.explanations import (
    FakeLLMClient,
    LLMProviderError,
    LLMProviderErrorDetails,
    LLMProviderFailureCategory,
)
from app.investigations.grounding_extraction import (
    GroundingExtractionError,
    GroundingExtractionFailureCode,
    GroundingExtractionInput,
    GroundingExtractionOutput,
    TypedGroundingExtractor,
)


def _extraction_input(**overrides: object) -> GroundingExtractionInput:
    fields: dict[str, object] = {
        "description": (
            "PR 42 in octo-org/analytics, deployment 52, checkout throwing errors"
        ),
    }
    fields.update(overrides)
    return GroundingExtractionInput.model_validate(fields)


def _expected_output() -> GroundingExtractionOutput:
    return GroundingExtractionOutput(
        repository_owner="octo-org",
        repository_name="analytics",
        deployment_reference="deployment:52",
        pull_request_number=42,
    )


class TypedGroundingExtractorTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_llm_returns_a_typed_extraction_from_a_known_text_sample(
        self,
    ) -> None:
        extracted = await TypedGroundingExtractor(
            FakeLLMClient(typed_output=_expected_output())
        ).extract(_extraction_input())

        self.assertEqual(extracted, _expected_output())

    async def test_provider_invalid_response_and_schema_failures_are_distinguishable(
        self,
    ) -> None:
        extraction_input = _extraction_input()

        class ProviderFailure:
            provider = FakeLLMClient.provider
            model = "failure"

            async def generate_typed(self, request):
                raise LLMProviderError(LLMProviderFailureCategory.CONNECTION)

        class MalformedResponse:
            provider = FakeLLMClient.provider
            model = "malformed"

            async def generate_typed(self, request):
                return object()

        for client, expected in (
            (ProviderFailure(), GroundingExtractionFailureCode.PROVIDER_FAILURE),
            (MalformedResponse(), GroundingExtractionFailureCode.INVALID_RESPONSE),
            (
                FakeLLMClient(typed_output={"repository_owner": 123}),
                GroundingExtractionFailureCode.EXTRACTION_SCHEMA_INVALID,
            ),
        ):
            with self.subTest(expected=expected):
                with self.assertRaises(GroundingExtractionError) as raised:
                    await TypedGroundingExtractor(client).extract(extraction_input)
                self.assertEqual(raised.exception.code, expected)

    async def test_provider_failure_preserves_safe_diagnostic_details(self) -> None:
        extraction_input = _extraction_input()
        details = LLMProviderErrorDetails(
            http_status=400,
            provider_type="invalid_request_error",
            provider_code="json_validate_failed",
            provider_message="Groq rejected generated structured output.",
            failed_generation_present=True,
            failed_generation_length=57,
        )

        class ProviderFailure:
            provider = FakeLLMClient.provider
            model = "failure"

            async def generate_typed(self, request):
                raise LLMProviderError(
                    LLMProviderFailureCategory.INVALID_REQUEST,
                    details,
                )

        with self.assertRaises(GroundingExtractionError) as raised:
            await TypedGroundingExtractor(ProviderFailure()).extract(extraction_input)

        self.assertEqual(
            raised.exception.code, GroundingExtractionFailureCode.PROVIDER_FAILURE
        )
        self.assertEqual(raised.exception.provider_details, details)
        self.assertEqual(
            raised.exception.provider_failure_category,
            LLMProviderFailureCategory.INVALID_REQUEST.value,
        )

    async def test_prompt_forbids_guessing_and_fabricated_claims(self) -> None:
        class RecordingClient:
            provider = FakeLLMClient.provider
            model = "recording"
            request = None

            async def generate_typed(self, request):
                self.request = request
                return {"output": _expected_output().model_dump(mode="json")}

        client = RecordingClient()
        await TypedGroundingExtractor(client).extract(_extraction_input())

        self.assertIn("never invent, guess", client.request.system_instructions)
        self.assertIn("leave it null", client.request.system_instructions)
        self.assertIn(
            "Do not create authoritative facts", client.request.system_instructions
        )

    async def test_prompt_omits_known_fields_section_when_nothing_is_known(
        self,
    ) -> None:
        class RecordingClient:
            provider = FakeLLMClient.provider
            model = "recording"
            request = None

            async def generate_typed(self, request):
                self.request = request
                return {"output": _expected_output().model_dump(mode="json")}

        client = RecordingClient()
        await TypedGroundingExtractor(client).extract(_extraction_input())

        self.assertNotIn("already confirmed", client.request.system_instructions)

    async def test_prompt_includes_known_fields_section_when_caller_supplied_any(
        self,
    ) -> None:
        class RecordingClient:
            provider = FakeLLMClient.provider
            model = "recording"
            request = None

            async def generate_typed(self, request):
                self.request = request
                return {"output": _expected_output().model_dump(mode="json")}

        client = RecordingClient()
        await TypedGroundingExtractor(client).extract(
            _extraction_input(known_repository_owner="octo-org")
        )

        self.assertIn("already confirmed", client.request.system_instructions)
        self.assertIn("repository_owner='octo-org'", client.request.system_instructions)


if __name__ == "__main__":
    unittest.main()
