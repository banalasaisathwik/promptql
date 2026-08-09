from app.explanations.models import (
    GeneratedExplanation,
    LLMStructuredResponse,
    LLMTokenUsage,
    MergeReadinessExplanationInput,
)


class FakeLLMClient:
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
            ),
        )
