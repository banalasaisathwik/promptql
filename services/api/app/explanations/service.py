from collections.abc import Callable
from hashlib import sha256
from time import perf_counter_ns

from pydantic import ValidationError

from app.explanations.errors import (
    ExplanationErrorCode,
    ExplanationValidationError,
    ExplanationValidationFailureCode,
    MergeReadinessExplanationError,
    LLMProviderError,
)
from app.explanations.models import (
    GeneratedExplanation,
    LLMStructuredResponse,
    LLMTokenUsage,
    LLMProviderName,
    MergeReadinessExplanation,
    MergeReadinessExplanationInput,
    ValidatedExplanation,
)
from app.explanations.instructions import PROMPT_ID, PROMPT_VERSION
from app.explanations.protocols import LLMClient
from app.explanations.templates import render_validated_explanation
from app.explanations.validator import (
    StrictMergeReadinessExplanationValidator,
)
from app.observability import (
    FailureCategory,
    LLMCallResult,
    NoOpRuntimeTelemetry,
    RuntimeTelemetry,
)
from app.policy import MergeReadinessResult


DurationClock = Callable[[], int]


def build_explanation_input(
    policy_result: MergeReadinessResult,
) -> MergeReadinessExplanationInput:
    return MergeReadinessExplanationInput(
        decision=policy_result.decision,
        primary_reason_code=policy_result.reason_code,
        blocker_reason_codes=tuple(
            blocker.reason_code for blocker in policy_result.blockers
        ),
        missing_information_reason_codes=tuple(
            finding.reason_code
            for finding in policy_result.missing_information
        ),
        pending_action_codes=tuple(
            action.action_code for action in policy_result.pending_actions
        ),
    )


class MergeReadinessExplanationService:
    def __init__(
        self,
        client: LLMClient,
        telemetry: RuntimeTelemetry | None = None,
        duration_clock: DurationClock = perf_counter_ns,
        validator: StrictMergeReadinessExplanationValidator | None = None,
    ) -> None:
        self._client = client
        self._telemetry = telemetry or NoOpRuntimeTelemetry()
        self._duration_clock = duration_clock
        self._validator = validator or StrictMergeReadinessExplanationValidator()

    @property
    def provider(self) -> LLMProviderName:
        return self._client.provider

    def _duration_ms(self, started_at_ns: int) -> int:
        elapsed_ns = max(0, self._duration_clock() - started_at_ns)
        return elapsed_ns // 1_000_000

    def _record_call(
        self,
        started_at_ns: int,
        result: LLMCallResult,
        token_usage: LLMTokenUsage | None,
    ) -> None:
        self._telemetry.record_llm_explanation(
            duration_ms=self._duration_ms(started_at_ns),
            result=result,
            input_tokens=(
                token_usage.input_tokens if token_usage is not None else None
            ),
            output_tokens=(
                token_usage.output_tokens if token_usage is not None else None
            ),
            total_tokens=(
                token_usage.total_tokens if token_usage is not None else None
            ),
            provider=self._client.provider.value,
        )

    def _validate_generated_output(
        self,
        policy_result: MergeReadinessResult,
        generated_output: object,
    ) -> ValidatedExplanation:
        try:
            generated = GeneratedExplanation.model_validate(generated_output)
        except ValidationError:
            raise ExplanationValidationError(
                ExplanationValidationFailureCode.INVALID_STRUCTURE
            ) from None
        return self._validator.validate(policy_result, generated)

    async def explain(
        self,
        policy_result: MergeReadinessResult,
    ) -> MergeReadinessExplanation:
        explanation_input = build_explanation_input(policy_result)
        started_at_ns = self._duration_clock()

        with self._telemetry.observe_llm_explanation(
            provider=self._client.provider.value,
            prompt_id=PROMPT_ID,
            prompt_version=PROMPT_VERSION,
            model_fingerprint=sha256(
                getattr(self._client, "model", "unreported").encode("utf-8")
            ).hexdigest()[:16],
        ) as observation:
            try:
                generated_response = await self._client.generate_structured(
                    explanation_input
                )
            except LLMProviderError as error:
                result = LLMCallResult.PROVIDER_FAILURE
                observation.set_attributes(
                    **{
                        "promptql.llm.result": result.value,
                        "promptql.llm.failure.category": error.category.value,
                    }
                )
                observation.mark_error(FailureCategory.LLM_PROVIDER_FAILURE)
                self._telemetry.record_llm_failure(
                    self._client.provider.value,
                    error.category.value,
                )
                self._record_call(started_at_ns, result, None)
                raise MergeReadinessExplanationError(
                    ExplanationErrorCode.PROVIDER_FAILURE,
                    "The explanation provider failed.",
                ) from None
            except Exception:
                result = LLMCallResult.PROVIDER_FAILURE
                observation.set_attributes(
                    **{"promptql.llm.result": result.value}
                )
                observation.mark_error(FailureCategory.LLM_PROVIDER_FAILURE)
                self._telemetry.record_llm_failure(
                    self._client.provider.value,
                    "unexpected",
                )
                self._record_call(started_at_ns, result, None)
                raise MergeReadinessExplanationError(
                    ExplanationErrorCode.PROVIDER_FAILURE,
                    "The explanation provider failed.",
                ) from None

            try:
                generated = LLMStructuredResponse.model_validate(
                    generated_response
                )
            except (TypeError, ValidationError):
                result = LLMCallResult.INVALID_OUTPUT
                observation.set_attributes(
                    **{"promptql.llm.result": result.value}
                )
                observation.mark_error(FailureCategory.LLM_INVALID_OUTPUT)
                self._record_call(started_at_ns, result, None)
                raise MergeReadinessExplanationError(
                    ExplanationErrorCode.INVALID_OUTPUT,
                    "The explanation provider returned invalid structured output.",
                ) from None

            try:
                validated = self._validate_generated_output(
                    policy_result,
                    generated.output,
                )
            except ExplanationValidationError as error:
                validation_failure = error.code
            else:
                result = LLMCallResult.SUCCESS
                safe_attributes: dict[str, str | int] = {
                    "promptql.llm.result": result.value,
                    "promptql.llm.validation.result": "success",
                }
                if generated.token_usage is not None:
                    safe_attributes.update(
                        {
                            "promptql.llm.input_tokens": (
                                generated.token_usage.input_tokens
                            ),
                            "promptql.llm.output_tokens": (
                                generated.token_usage.output_tokens
                            ),
                        }
                    )
                    if generated.token_usage.total_tokens is not None:
                        safe_attributes["promptql.llm.total_tokens"] = (
                            generated.token_usage.total_tokens
                        )
                observation.set_attributes(**safe_attributes)
                self._record_call(
                    started_at_ns,
                    result,
                    generated.token_usage,
                )
                return render_validated_explanation(validated)

            result = LLMCallResult.VALIDATION_FAILURE
            observation.set_attributes(
                **{
                    "promptql.llm.result": result.value,
                    "promptql.llm.validation.result": "failure",
                    "promptql.llm.validation.failure_category": (
                        validation_failure.value
                    ),
                }
            )
            observation.mark_error(FailureCategory.LLM_VALIDATION_FAILURE)
            self._record_call(started_at_ns, result, generated.token_usage)
            raise MergeReadinessExplanationError(
                ExplanationErrorCode.VALIDATION_FAILED,
                "The generated explanation did not pass validation.",
            ) from None
