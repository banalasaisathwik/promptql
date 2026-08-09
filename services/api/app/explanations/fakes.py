from app.explanations.models import (
    LLMStructuredResponse,
    LLMTokenUsage,
    MergeReadinessExplanationInput,
)
from app.explanations.templates import build_strict_explanation


class FakeLLMClient:
    async def generate_structured(
        self,
        explanation_input: MergeReadinessExplanationInput,
    ) -> LLMStructuredResponse:
        explanation = build_strict_explanation(explanation_input)
        input_token_count = (
            2
            + len(explanation_input.blocker_reason_codes)
            + len(explanation_input.missing_information_reason_codes)
            + len(explanation_input.pending_action_codes)
        )
        output_token_count = (
            1 + len(explanation.reasons) + len(explanation.recommended_actions)
        )

        return LLMStructuredResponse(
            output=explanation.model_dump(mode="json"),
            token_usage=LLMTokenUsage(
                input_tokens=input_token_count,
                output_tokens=output_token_count,
            ),
        )
