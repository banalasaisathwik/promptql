from app.explanations.models import (
    MergeReadinessExplanation,
    MergeReadinessExplanationInput,
)
from app.explanations.templates import build_strict_explanation


class StrictExplanationValidationError(ValueError):
    pass


class StrictMergeReadinessExplanationValidator:
    def validate(
        self,
        explanation_input: MergeReadinessExplanationInput,
        explanation: MergeReadinessExplanation,
    ) -> MergeReadinessExplanation:
        expected = build_strict_explanation(explanation_input)
        if explanation != expected:
            raise StrictExplanationValidationError(
                "Generated explanation did not match the accepted template."
            )
        return explanation
