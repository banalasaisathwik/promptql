"""Provider-neutral generation of untrusted, structured hypothesis candidates."""

from pydantic import ValidationError

from app.explanations import LLMProviderError, LLMStructuredResponse, TypedLLMClient, TypedLLMRequest
from app.investigations.hypotheses.errors import HypothesisGenerationError
from app.investigations.hypotheses.instructions import HYPOTHESIS_PROMPT_ID, HYPOTHESIS_PROMPT_VERSION, HYPOTHESIS_SYSTEM_INSTRUCTIONS
from app.investigations.hypotheses.models import (
    GeneratedHypotheses,
    HypothesisGenerationFailureCode,
    HypothesisGenerationInput,
    HypothesisGenerationMetadata,
    HypothesisGenerationOutput,
)


class TypedLLMHypothesisGenerator:
    """Request candidates through the shared LLM boundary; never trust or validate them."""

    def __init__(self, client: TypedLLMClient) -> None:
        self._client = client

    # PURPOSE: Convert a provider proposal into the narrow candidate contract,
    # without deciding whether the causal interpretation is supported.
    #
    # FLOW: Send minimized Facts through the shared typed LLM interface -> check
    # its outer envelope -> validate the candidate schema -> attach safe prompt
    # metadata. The deterministic validator receives the result later.
    #
    # WHY: A Pydantic-shaped response proves only structure. Keeping semantic
    # acceptance out of this class prevents an LLM call from becoming authority.
    async def generate(
        self, generation_input: HypothesisGenerationInput
    ) -> GeneratedHypotheses:
        # Provider/network failure is deliberately separate from malformed model
        # output so a caller can observe the boundary that actually failed.
        try:
            response = await self._client.generate_typed(
                TypedLLMRequest(
                    system_instructions=HYPOTHESIS_SYSTEM_INSTRUCTIONS,
                    input=generation_input,
                    output_model=HypothesisGenerationOutput,
                )
            )
        except LLMProviderError:
            raise HypothesisGenerationError(
                HypothesisGenerationFailureCode.PROVIDER_FAILURE
            ) from None
        except Exception:
            raise HypothesisGenerationError(
                HypothesisGenerationFailureCode.PROVIDER_FAILURE
            ) from None

        # `model_validate()` is runtime validation (unlike a TypeScript type): it
        # proves the provider returned the expected outer structured envelope.
        try:
            structured = LLMStructuredResponse.model_validate(response)
        except (TypeError, ValidationError):
            raise HypothesisGenerationError(
                HypothesisGenerationFailureCode.INVALID_RESPONSE
            ) from None
        try:
            output = HypothesisGenerationOutput.model_validate(structured.output)
        except ValidationError:
            raise HypothesisGenerationError(
                HypothesisGenerationFailureCode.CANDIDATE_SCHEMA_INVALID
            ) from None

        return GeneratedHypotheses(
            candidates=output.candidates,
            metadata=HypothesisGenerationMetadata(
                provider=self._client.provider.value,
                model=self._client.model,
                prompt_id=HYPOTHESIS_PROMPT_ID,
                prompt_version=HYPOTHESIS_PROMPT_VERSION,
            ),
        )
