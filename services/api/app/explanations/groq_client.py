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
    TypedLLMRequest,
)


class ChatCompletionsAPI(Protocol):
    async def parse(self, **request: object) -> object: ...


class ChatAPI(Protocol):
    completions: ChatCompletionsAPI


class BetaAPI(Protocol):
    chat: ChatAPI


class GroqSDKClient(Protocol):
    beta: BetaAPI

    async def close(self) -> None: ...


class GroqLLMClient:
    provider = LLMProviderName.GROQ

    def __init__(
        self,
        client: GroqSDKClient,
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
    def _token_usage(response: object) -> LLMTokenUsage | None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        try:
            return LLMTokenUsage(
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
            )
        except (AttributeError, TypeError, ValidationError):
            return None

    @staticmethod
    def _first_message(response: object) -> object | None:
        choices: Sequence[object] = getattr(response, "choices", None) or ()
        if not choices:
            return None
        return getattr(choices[0], "message", None)

    async def generate_structured(
        self,
        explanation_input: MergeReadinessExplanationInput,
    ) -> LLMStructuredResponse:
        try:
            response = await self._client.beta.chat.completions.parse(
                model=self._model,
                messages=(
                    {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                    {
                        "role": "user",
                        "content": explanation_input.model_dump_json(),
                    },
                ),
                response_format=GeneratedExplanation,
                max_tokens=self._max_output_tokens,
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
            message = self._first_message(response)
            parsed_output = getattr(message, "parsed", None)
            if getattr(message, "refusal", None):
                category = LLMProviderFailureCategory.REFUSAL
            elif parsed_output is None:
                category = LLMProviderFailureCategory.INVALID_STRUCTURED_RESPONSE
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

    async def generate_typed(
        self,
        request: TypedLLMRequest,
    ) -> LLMStructuredResponse:
        # Keep Groq's chat-completions syntax inside its adapter while sharing the
        # same validated request contract used by other providers.
        try:
            response = await self._client.beta.chat.completions.parse(
                model=self._model,
                messages=(
                    {"role": "system", "content": request.system_instructions},
                    {"role": "user", "content": request.input.model_dump_json()},
                ),
                response_format=request.output_model,
                max_tokens=self._max_output_tokens,
                timeout=self._request_timeout_seconds,
            )
        except OpenAIError:
            raise LLMProviderError(LLMProviderFailureCategory.UPSTREAM_UNAVAILABLE) from None
        message = self._first_message(response)
        parsed_output = getattr(message, "parsed", None)
        if getattr(message, "refusal", None):
            raise LLMProviderError(LLMProviderFailureCategory.REFUSAL)
        if parsed_output is None:
            raise LLMProviderError(LLMProviderFailureCategory.INVALID_STRUCTURED_RESPONSE)
        return LLMStructuredResponse(
            output=parsed_output.model_dump(mode="json")
            if hasattr(parsed_output, "model_dump")
            else parsed_output,
            token_usage=self._token_usage(response),
        )
