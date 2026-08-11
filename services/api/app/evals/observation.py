from time import perf_counter_ns

from pydantic import ValidationError

from app.evals.cases import ExplanationObservationCase
from app.evals.models import (
    EvalRunIdentity,
    ExplanationObservationRecord,
    ValidatorResult,
)
from app.explanations import (
    ExplanationValidationError,
    GeneratedExplanation,
    LLMClient,
    LLMProviderError,
    LLMStructuredResponse,
    StrictMergeReadinessExplanationValidator,
    build_explanation_input,
    required_explanation_claims,
)
from app.policy import evaluate_merge_readiness


def _elapsed_ms(started_at_ns: int) -> int:
    return max(0, perf_counter_ns() - started_at_ns) // 1_000_000


async def observe_case(
    case: ExplanationObservationCase,
    client: LLMClient,
    *,
    run_identity: EvalRunIdentity,
    sample_number: int,
) -> ExplanationObservationRecord:
    policy_result = evaluate_merge_readiness(case.github, case.jira)
    expected = required_explanation_claims(policy_result)
    explanation_input = build_explanation_input(policy_result)
    started_at_ns = perf_counter_ns()

    observed: GeneratedExplanation | None = None
    token_usage = None
    provider_success = False
    candidate_returned = False
    schema_valid = False
    validator_result = ValidatorResult.NOT_RUN
    failure_category: str | None = None

    try:
        raw_response = await client.generate_structured(explanation_input)
    except LLMProviderError as error:
        failure_category = error.category.value
    except Exception:
        failure_category = "unexpected"
    else:
        provider_success = True
        try:
            structured_response = LLMStructuredResponse.model_validate(raw_response)
        except (TypeError, ValidationError):
            failure_category = "invalid_structure"
        else:
            candidate_returned = True
            token_usage = structured_response.token_usage
            try:
                observed = GeneratedExplanation.model_validate(
                    structured_response.output
                )
            except ValidationError:
                failure_category = "invalid_structure"
            else:
                schema_valid = True
                try:
                    StrictMergeReadinessExplanationValidator().validate(
                        policy_result,
                        observed,
                    )
                except ExplanationValidationError as error:
                    validator_result = ValidatorResult.FAILED
                    failure_category = error.code.value
                else:
                    validator_result = ValidatorResult.PASSED

    return ExplanationObservationRecord(
        case_id=case.case_id,
        prompt_id=run_identity.prompt_id,
        prompt_version=run_identity.prompt_version,
        dataset_id=run_identity.dataset_id,
        dataset_version=run_identity.dataset_version,
        dataset_split=run_identity.dataset_split,
        provider=client.provider,
        configured_model=run_identity.configured_model,
        model_settings=run_identity.model_settings,
        sample_number=sample_number,
        expected_decision=expected.decision,
        expected_reason_codes=expected.reason_codes,
        expected_action_codes=expected.action_codes,
        observed_decision=observed.decision if observed is not None else None,
        observed_reason_codes=(observed.reason_codes if observed is not None else ()),
        observed_action_codes=(observed.action_codes if observed is not None else ()),
        provider_success=provider_success,
        candidate_returned=candidate_returned,
        schema_valid=schema_valid,
        validator_result=validator_result,
        sanitized_failure_category=failure_category,
        latency_ms=_elapsed_ms(started_at_ns),
        token_usage=token_usage,
    )


def main() -> int:
    from app.evals.runner import main as runner_main

    return runner_main()


if __name__ == "__main__":
    raise SystemExit(main())
