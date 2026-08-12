from collections.abc import Sequence
from typing import Protocol

from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ContentFilterFinishReasonError,
    InternalServerError,
    LengthFinishReasonError,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)
from pydantic import ValidationError

from app.explanations.errors import (
    LLMProviderError,
    LLMProviderFailureCategory,
)
from app.explanations.instructions import SYSTEM_INSTRUCTIONS
from app.explanations.models import (
    GeneratedExplanation,
    LLMProviderName,
    LLMStructuredResponse,
    LLMTokenUsage,
    MergeReadinessExplanationInput,
)


class ResponsesAPI(Protocol):
    async def parse(self, **request: object) -> object: ...


class OpenAISDKClient(Protocol):
    responses: ResponsesAPI

    async def close(self) -> None: ...


class OpenAILLMClient:
    provider = LLMProviderName.OPENAI

    def __init__(
        self,
        client: OpenAISDKClient,
        model: str,
        request_timeout_seconds: float,
        max_output_tokens: int,
    ) -> None:
        self._client = client
        self._model = model
        self._request_timeout_seconds = request_timeout_seconds
        self._max_output_tokens = max_output_tokens

    async def aclose(self) -> None:
        await self._client.close()

    @property
    def model(self) -> str:
        return self._model

    @staticmethod
    def _contains_refusal(response: object) -> bool:
        output: Sequence[object] = getattr(response, "output", ())
        for output_item in output:
            content: Sequence[object] = getattr(output_item, "content", ())
            if any(getattr(part, "type", None) == "refusal" for part in content):
                return True
        return False

    @staticmethod
    def _token_usage(response: object) -> LLMTokenUsage | None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        try:
            return LLMTokenUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
            )
        except (AttributeError, TypeError, ValidationError):
            return None

    async def generate_structured(
        self,
        explanation_input: MergeReadinessExplanationInput,
    ) -> LLMStructuredResponse:
        try:
            response = await self._client.responses.parse(
                model=self._model,
                instructions=SYSTEM_INSTRUCTIONS,
                input=explanation_input.model_dump_json(),
                text_format=GeneratedExplanation,
                store=False,
                max_output_tokens=self._max_output_tokens,
                timeout=self._request_timeout_seconds,
            )
        except AuthenticationError:
            category = LLMProviderFailureCategory.AUTHENTICATION
        except PermissionDeniedError:
            category = LLMProviderFailureCategory.PERMISSION
        except RateLimitError:
            category = LLMProviderFailureCategory.RATE_LIMIT
        except APITimeoutError:
            category = LLMProviderFailureCategory.TIMEOUT
        except APIConnectionError:
            category = LLMProviderFailureCategory.CONNECTION
        except (BadRequestError, UnprocessableEntityError):
            category = LLMProviderFailureCategory.INVALID_REQUEST
        except ContentFilterFinishReasonError:
            category = LLMProviderFailureCategory.REFUSAL
        except (LengthFinishReasonError, APIResponseValidationError):
            category = LLMProviderFailureCategory.INVALID_STRUCTURED_RESPONSE
        except InternalServerError:
            category = LLMProviderFailureCategory.UPSTREAM_UNAVAILABLE
        except APIStatusError as error:
            category = (
                LLMProviderFailureCategory.UPSTREAM_UNAVAILABLE
                if error.status_code >= 500
                else LLMProviderFailureCategory.INVALID_REQUEST
            )
        except OpenAIError:
            category = LLMProviderFailureCategory.UPSTREAM_UNAVAILABLE
        else:
            parsed_output = getattr(response, "output_parsed", None)
            if parsed_output is None:
                category = (
                    LLMProviderFailureCategory.REFUSAL
                    if self._contains_refusal(response)
                    else LLMProviderFailureCategory.INVALID_STRUCTURED_RESPONSE
                )
            else:
                try:
                    generated = GeneratedExplanation.model_validate(parsed_output)
                except ValidationError:
                    category = (
                        LLMProviderFailureCategory.INVALID_STRUCTURED_RESPONSE
                    )
                else:
                    return LLMStructuredResponse(
                        output=generated.model_dump(mode="json"),
                        token_usage=self._token_usage(response),
                    )

        raise LLMProviderError(category) from None
