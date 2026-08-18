from app.explanations.models import (
    GeneratedExplanation,
    LLMProviderName,
    LLMStructuredResponse,
    LLMTokenUsage,
    MergeReadinessExplanationInput,
    TypedLLMRequest,
)


class FakeLLMClient:
    provider = LLMProviderName.FAKE
    model = "deterministic-fake-v1"

    def __init__(self, typed_output: object | None = None) -> None:
        self._typed_output = typed_output

    async def generate_structured(
        self,
        explanation_input: MergeReadinessExplanationInput,
    ) -> LLMStructuredResponse:
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
            summary="This deterministic fake prose is intentionally discarded.",
            reason_codes=reason_codes,
            action_codes=tuple(
                dict.fromkeys(explanation_input.pending_action_codes)
            ),
        )
        input_token_count = (
            2
            + len(explanation_input.blocker_reason_codes)
            + len(explanation_input.missing_information_reason_codes)
            + len(explanation_input.pending_action_codes)
        )
        output_token_count = (
            1 + len(generated.reason_codes) + len(generated.action_codes)
        )

        return LLMStructuredResponse(
            output=generated.model_dump(mode="json"),
            token_usage=LLMTokenUsage(
                input_tokens=input_token_count,
                output_tokens=output_token_count,
                total_tokens=input_token_count + output_token_count,
            ),
        )

    async def generate_typed(
        self,
        request: TypedLLMRequest,
    ) -> LLMStructuredResponse:
        # A test must opt in to its candidate output. The default failure keeps a
        # fake from silently inventing a plan that production code never supplied.
        if self._typed_output is None:
            from app.explanations.errors import (
                LLMProviderError,
                LLMProviderFailureCategory,
            )

            raise LLMProviderError(
                LLMProviderFailureCategory.INVALID_STRUCTURED_RESPONSE
            )
        output = self._typed_output
        if hasattr(output, "model_dump"):
            output = output.model_dump(mode="json")
        return LLMStructuredResponse(output=output)
