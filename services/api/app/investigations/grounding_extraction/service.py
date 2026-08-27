from pydantic import ValidationError

from app.explanations import (
    LLMProviderError,
    LLMStructuredResponse,
    TypedLLMClient,
    TypedLLMRequest,
)
from app.investigations.grounding_extraction.errors import GroundingExtractionError
from app.investigations.grounding_extraction.instructions import (
    build_grounding_extraction_system_instructions,
)
from app.investigations.grounding_extraction.models import (
    GroundingExtractionFailureCode,
    GroundingExtractionInput,
    GroundingExtractionOutput,
)


class TypedGroundingExtractor:
    def __init__(self, client: TypedLLMClient) -> None:
        self._client = client

    async def extract(
        self, extraction_input: GroundingExtractionInput
    ) -> GroundingExtractionOutput:
        try:
            response = await self._client.generate_typed(
                TypedLLMRequest(
                    system_instructions=build_grounding_extraction_system_instructions(
                        extraction_input
                    ),
                    input=extraction_input,
                    output_model=GroundingExtractionOutput,
                )
            )
        except LLMProviderError as error:
            raise GroundingExtractionError(
                GroundingExtractionFailureCode.PROVIDER_FAILURE,
                "The grounding extraction provider failed.",
                provider_details=error.details,
                provider_failure_category=error.category.value,
            ) from None
        except Exception:
            raise GroundingExtractionError(
                GroundingExtractionFailureCode.PROVIDER_FAILURE,
                "The grounding extraction provider failed.",
            ) from None

        try:
            structured = LLMStructuredResponse.model_validate(response)
        except (TypeError, ValidationError):
            raise GroundingExtractionError(
                GroundingExtractionFailureCode.INVALID_RESPONSE,
                "The grounding extraction provider returned an invalid structured response.",
            ) from None
        try:
            return GroundingExtractionOutput.model_validate(structured.output)
        except ValidationError:
            raise GroundingExtractionError(
                GroundingExtractionFailureCode.EXTRACTION_SCHEMA_INVALID,
                "The extraction proposal did not match the grounding schema.",
            ) from None
