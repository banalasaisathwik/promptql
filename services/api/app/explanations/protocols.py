from typing import Protocol

from app.explanations.models import (
    LLMProviderName,
    LLMStructuredResponse,
    MergeReadinessExplanationInput,
)


class LLMClient(Protocol):
    provider: LLMProviderName
    model: str

    async def generate_structured(
        self,
        explanation_input: MergeReadinessExplanationInput,
    ) -> LLMStructuredResponse: ...
