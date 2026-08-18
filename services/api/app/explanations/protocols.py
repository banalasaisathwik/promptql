from typing import Protocol

from app.explanations.models import (
    LLMProviderName,
    LLMStructuredResponse,
    MergeReadinessExplanationInput,
    TypedLLMRequest,
)


class LLMClient(Protocol):
    provider: LLMProviderName
    model: str

    async def generate_structured(
        self,
        explanation_input: MergeReadinessExplanationInput,
    ) -> LLMStructuredResponse: ...


class TypedLLMClient(Protocol):
    # PURPOSE: Define the structural interface used by new typed LLM tasks.
    # Like a TypeScript interface, Protocol describes the required shape, but
    # concrete providers still perform their own runtime SDK calls and parsing.
    provider: LLMProviderName
    model: str

    async def generate_typed(
        self,
        request: TypedLLMRequest,
    ) -> LLMStructuredResponse: ...
