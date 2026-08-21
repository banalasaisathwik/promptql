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
    LLMProviderErrorDetails,
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
    _typed_reasoning_effort: str | None = "low"
    _diagnostic_provider_name = "Groq"

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

    # PURPOSE: Translate an SDK/provider error into an explicit allowlist.
    #
    # SECURITY: The raw body and failed generation are inspected only to derive
    # stable type/code fields and a length. Neither payload crosses this method.
    @classmethod
    def _safe_error_details(cls, error: Exception) -> LLMProviderErrorDetails | None:
        """Keep diagnostic fields useful without retaining a provider payload."""
        status_code = getattr(error, "status_code", None)
        body = getattr(error, "body", None)
        payload = body if isinstance(body, dict) else {}
        provider_error = payload.get("error")
        provider_error = (
            provider_error if isinstance(provider_error, dict) else payload
        )
        provider_type = provider_error.get("type")
        provider_code = provider_error.get("code")
        failed_generation = provider_error.get("failed_generation")
        if not any(
            (
                isinstance(status_code, int),
                isinstance(provider_type, str),
                isinstance(provider_code, str),
                isinstance(failed_generation, str),
            )
        ):
            return None
        return LLMProviderErrorDetails(
            http_status=status_code if isinstance(status_code, int) else None,
            provider_type=provider_type if isinstance(provider_type, str) else None,
            provider_code=provider_code if isinstance(provider_code, str) else None,
            provider_message=(
                f"{cls._diagnostic_provider_name} rejected generated structured output."
                if provider_code == "json_validate_failed"
                else None
            ),
            failed_generation_present=isinstance(failed_generation, str),
            failed_generation_length=(
                len(failed_generation)
                if isinstance(failed_generation, str)
                else None
            ),
        )

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
            # Build the request separately so an inherited compatibility adapter
            # can omit Groq-only options without duplicating typed parsing logic.
            typed_request: dict[str, object] = {
                "model": self._model,
                "messages": (
                    {"role": "system", "content": request.system_instructions},
                    {"role": "user", "content": request.input.model_dump_json()},
                ),
                "response_format": request.output_model,
                "max_tokens": self._max_output_tokens,
                "timeout": self._request_timeout_seconds,
            }
            if self._typed_reasoning_effort is not None:
                typed_request["reasoning_effort"] = self._typed_reasoning_effort
            response = await self._client.beta.chat.completions.parse(
                **typed_request,
            )
        except AuthenticationError:
            raise LLMProviderError(LLMProviderFailureCategory.AUTHENTICATION) from None
        except PermissionDeniedError:
            raise LLMProviderError(LLMProviderFailureCategory.PERMISSION) from None
        except RateLimitError:
            # The runtime owns retries. The adapter makes one attempt and
            # preserves the typed rate-limit category for that policy layer.
            raise LLMProviderError(LLMProviderFailureCategory.RATE_LIMIT) from None
        except APITimeoutError:
            raise LLMProviderError(LLMProviderFailureCategory.TIMEOUT) from None
        except APIConnectionError:
            raise LLMProviderError(LLMProviderFailureCategory.CONNECTION) from None
        except (BadRequestError, UnprocessableEntityError) as error:
            raise LLMProviderError(
                LLMProviderFailureCategory.INVALID_REQUEST,
                self._safe_error_details(error),
            ) from None
        except ContentFilterFinishReasonError:
            raise LLMProviderError(LLMProviderFailureCategory.REFUSAL) from None
        except LengthFinishReasonError:
            raise LLMProviderError(
                LLMProviderFailureCategory.INVALID_STRUCTURED_RESPONSE,
                LLMProviderErrorDetails(
                    provider_code="length_finish_reason",
                    provider_message=(
                        f"{self._diagnostic_provider_name} ended structured generation at the output limit."
                    ),
                ),
            ) from None
        except APIResponseValidationError:
            raise LLMProviderError(
                LLMProviderFailureCategory.INVALID_STRUCTURED_RESPONSE
            ) from None
        except InternalServerError:
            raise LLMProviderError(
                LLMProviderFailureCategory.UPSTREAM_UNAVAILABLE
            ) from None
        except APIStatusError as error:
            category = (
                LLMProviderFailureCategory.UPSTREAM_UNAVAILABLE
                if error.status_code >= 500
                else LLMProviderFailureCategory.INVALID_REQUEST
            )
            raise LLMProviderError(category, self._safe_error_details(error)) from None
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
