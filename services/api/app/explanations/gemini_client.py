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
from pydantic import BaseModel, ValidationError

from app.explanations.errors import (
    LLMProviderError,
    LLMProviderFailureCategory,
)
from app.explanations.models import (
    GeneratedExplanation,
    LLMProviderName,
    LLMStructuredResponse,
    LLMTokenUsage,
    MergeReadinessExplanationInput,
)


GEMINI_SYSTEM_INSTRUCTIONS = (
    "Return structured merge-readiness claims only. Copy decision exactly. "
    "reason_indexes must contain every zero-based index from "
    "required_reason_codes exactly once. action_indexes must contain every "
    "zero-based index from pending_action_codes exactly once. Do not invent "
    "indexes. Write a short non-empty summary; it will be discarded."
)


class ChatCompletionsAPI(Protocol):
    async def parse(self, **request: object) -> object: ...


class ChatAPI(Protocol):
    completions: ChatCompletionsAPI


class BetaAPI(Protocol):
    chat: ChatAPI


class GeminiSDKClient(Protocol):
    beta: BetaAPI

    async def close(self) -> None: ...


class GeminiStructuredClaims(BaseModel):
    decision: str
    summary: str
    reason_indexes: list[int]
    action_indexes: list[int]


class GeminiExplanationInput(BaseModel):
    decision: str
    required_reason_codes: list[str]
    pending_action_codes: list[str]


class GeminiLLMClient:
    provider = LLMProviderName.GEMINI

    def __init__(
        self,
        client: GeminiSDKClient,
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

    @staticmethod
    def _is_invalid_api_key_response(body: object) -> bool:
        if isinstance(body, str):
            return "please pass a valid api key" in body.lower()
        if isinstance(body, dict):
            return any(
                GeminiLLMClient._is_invalid_api_key_response(value)
                for value in body.values()
            )
        if isinstance(body, (list, tuple)):
            return any(
                GeminiLLMClient._is_invalid_api_key_response(value)
                for value in body
            )
        return False

    @staticmethod
    def _provider_input(
        explanation_input: MergeReadinessExplanationInput,
    ) -> GeminiExplanationInput:
        required_reason_codes = tuple(
            dict.fromkeys(
                (
                    *explanation_input.blocker_reason_codes,
                    *explanation_input.missing_information_reason_codes,
                )
            )
        ) or (explanation_input.primary_reason_code,)
        pending_action_codes = tuple(
            dict.fromkeys(explanation_input.pending_action_codes)
        )
        return GeminiExplanationInput(
            decision=explanation_input.decision.value,
            required_reason_codes=[code.value for code in required_reason_codes],
            pending_action_codes=[code.value for code in pending_action_codes],
        )

    @staticmethod
    def _map_indexes(indexes: list[int], values: list[str]) -> tuple[str, ...]:
        if len(indexes) != len(set(indexes)):
            raise ValueError("duplicate provider index")
        if any(index < 0 or index >= len(values) for index in indexes):
            raise ValueError("provider index is outside the allowlist")
        return tuple(values[index] for index in indexes)

    async def generate_structured(
        self,
        explanation_input: MergeReadinessExplanationInput,
    ) -> LLMStructuredResponse:
        provider_input = self._provider_input(explanation_input)
        try:
            response = await self._client.beta.chat.completions.parse(
                model=self._model,
                messages=(
                    {"role": "system", "content": GEMINI_SYSTEM_INSTRUCTIONS},
                    {
                        "role": "user",
                        "content": provider_input.model_dump_json(),
                    },
                ),


                response_format=GeminiStructuredClaims,
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
        except BadRequestError as error:
            category = (
                LLMProviderFailureCategory.AUTHENTICATION
                if self._is_invalid_api_key_response(error.body)
                else LLMProviderFailureCategory.INVALID_REQUEST
            )
        except UnprocessableEntityError:
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
                    claims = GeminiStructuredClaims.model_validate(parsed_output)
                    generated = GeneratedExplanation(
                        decision=claims.decision,
                        summary=claims.summary,
                        reason_codes=self._map_indexes(
                            claims.reason_indexes,
                            provider_input.required_reason_codes,
                        ),
                        action_codes=self._map_indexes(
                            claims.action_indexes,
                            provider_input.pending_action_codes,
                        ),
                    )
                except (ValidationError, ValueError):
                    category = (
                        LLMProviderFailureCategory.INVALID_STRUCTURED_RESPONSE
                    )
                else:
                    return LLMStructuredResponse(
                        output=generated.model_dump(mode="json"),
                        token_usage=self._token_usage(response),
                    )

        raise LLMProviderError(category) from None
