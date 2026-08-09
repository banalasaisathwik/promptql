from typing import Protocol

from app.explanations.models import (
    LLMStructuredResponse,
    MergeReadinessExplanationInput,
)


class LLMClient(Protocol):
    async def generate_structured(
        self,
        explanation_input: MergeReadinessExplanationInput,
    ) -> LLMStructuredResponse: ...
