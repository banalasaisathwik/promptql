from pydantic import ValidationError

from app.explanations import (
    LLMProviderError,
    LLMStructuredResponse,
    TypedLLMClient,
    TypedLLMRequest,
)
from app.investigations.code_diagnosis.errors import CodeDiagnosisError
from app.investigations.code_diagnosis.instructions import (
    CODE_DIAGNOSIS_PROMPT_ID,
    CODE_DIAGNOSIS_PROMPT_VERSION,
    CODE_DIAGNOSIS_SYSTEM_INSTRUCTIONS,
)
from app.investigations.code_diagnosis.models import (
    CodeDiagnosisFailureCode,
    CodeDiagnosisInput,
    CodeDiagnosisMetadata,
    CodeDiagnosisOutput,
    GeneratedCodeFindings,
)


class TypedLLMCodeDiagnoser:
    def __init__(self, client: TypedLLMClient) -> None:
        self._client = client

    async def generate(
        self,
        diagnosis_input: CodeDiagnosisInput,
    ) -> GeneratedCodeFindings:
        try:
            response = await self._client.generate_typed(
                TypedLLMRequest(
                    system_instructions=CODE_DIAGNOSIS_SYSTEM_INSTRUCTIONS,
                    input=diagnosis_input,
                    output_model=CodeDiagnosisOutput,
                )
            )
        except LLMProviderError as error:
            raise CodeDiagnosisError(
                CodeDiagnosisFailureCode.PROVIDER_FAILURE,
                provider_details=error.details,
                provider_failure_category=error.category.value,
            ) from None
        except Exception:
            raise CodeDiagnosisError(CodeDiagnosisFailureCode.PROVIDER_FAILURE) from None

        try:
            structured = LLMStructuredResponse.model_validate(response)
        except (TypeError, ValidationError):
            raise CodeDiagnosisError(CodeDiagnosisFailureCode.INVALID_RESPONSE) from None
        try:
            output = CodeDiagnosisOutput.model_validate(structured.output)
        except ValidationError:
            raise CodeDiagnosisError(
                CodeDiagnosisFailureCode.CANDIDATE_SCHEMA_INVALID
            ) from None

        return GeneratedCodeFindings(
            candidates=output.candidates,
            metadata=CodeDiagnosisMetadata(
                provider=self._client.provider.value,
                model=self._client.model,
                requested_model=self._client.model,
                resolved_model=structured.resolved_model,
                prompt_id=CODE_DIAGNOSIS_PROMPT_ID,
                prompt_version=CODE_DIAGNOSIS_PROMPT_VERSION,
                token_usage=structured.token_usage,
            ),
        )
