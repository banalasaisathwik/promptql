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
    def __init__(self, client: TypedLLMClient) -> None:
        self._client = client


    async def generate(
        self, generation_input: HypothesisGenerationInput
    ) -> GeneratedHypotheses:
        try:
            response = await self._client.generate_typed(
                TypedLLMRequest(
                    system_instructions=HYPOTHESIS_SYSTEM_INSTRUCTIONS,
                    input=generation_input,
                    output_model=HypothesisGenerationOutput,
                )
            )
        except LLMProviderError as error:
            raise HypothesisGenerationError(
                HypothesisGenerationFailureCode.PROVIDER_FAILURE,
                provider_details=error.details,
                provider_failure_category=error.category.value,
            ) from None
        except Exception:
            raise HypothesisGenerationError(
                HypothesisGenerationFailureCode.PROVIDER_FAILURE
            ) from None


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
                task="hypothesis_generation",
                provider=self._client.provider.value,
                model=self._client.model,
                requested_model=self._client.model,
                resolved_model=structured.resolved_model,
                prompt_id=HYPOTHESIS_PROMPT_ID,
                prompt_version=HYPOTHESIS_PROMPT_VERSION,
                token_usage=structured.token_usage,
            ),
        )
