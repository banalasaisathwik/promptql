from app.explanations.errors import (
    ExplanationValidationError,
    ExplanationValidationFailureCode,
)
from app.explanations.models import (
    GeneratedExplanation,
    ValidatedExplanation,
)
from app.policy import (
    MergeReadinessDecision,
    MergeReadinessResult,
    PendingActionCode,
    PolicyReasonCode,
)


def _required_reason_codes(
    policy_result: MergeReadinessResult,
) -> tuple[PolicyReasonCode, ...]:
    finding_codes = tuple(
        finding.reason_code
        for finding in (
            *policy_result.blockers,
            *policy_result.missing_information,
        )
    )
    if not finding_codes:
        finding_codes = (policy_result.reason_code,)
    return tuple(dict.fromkeys(finding_codes))


def _required_action_codes(
    policy_result: MergeReadinessResult,
) -> tuple[PendingActionCode, ...]:
    action_codes = tuple(
        action.action_code for action in policy_result.pending_actions
    )
    return tuple(dict.fromkeys(action_codes))


def required_explanation_claims(
    policy_result: MergeReadinessResult,
) -> ValidatedExplanation:
    return ValidatedExplanation(
        decision=policy_result.decision,
        reason_codes=_required_reason_codes(policy_result),
        action_codes=_required_action_codes(policy_result),
    )


def _raise(code: ExplanationValidationFailureCode) -> None:
    raise ExplanationValidationError(code)


class StrictMergeReadinessExplanationValidator:
    def validate(
        self,
        policy_result: MergeReadinessResult,
        generated: GeneratedExplanation,
    ) -> ValidatedExplanation:
        required_claims = required_explanation_claims(policy_result)

        if generated.decision is not policy_result.decision:
            _raise(ExplanationValidationFailureCode.DECISION_MISMATCH)

        if len(generated.reason_codes) != len(set(generated.reason_codes)):
            _raise(ExplanationValidationFailureCode.DUPLICATE_REASON)
        if len(generated.action_codes) != len(set(generated.action_codes)):
            _raise(ExplanationValidationFailureCode.DUPLICATE_ACTION)

        generated_reasons = set(generated.reason_codes)
        generated_actions = set(generated.action_codes)
        required_reasons = required_claims.reason_codes
        required_actions = required_claims.action_codes
        required_reason_set = set(required_reasons)
        required_action_set = set(required_actions)


        if policy_result.decision is MergeReadinessDecision.READY and (
            generated_reasons != {PolicyReasonCode.READY}
            or bool(generated_actions)
        ):
            _raise(ExplanationValidationFailureCode.CONTRADICTORY_CLAIM)
        if (
            policy_result.decision is not MergeReadinessDecision.READY
            and PolicyReasonCode.READY in generated_reasons
        ):
            _raise(ExplanationValidationFailureCode.CONTRADICTORY_CLAIM)
        if (
            policy_result.decision is MergeReadinessDecision.UNKNOWN
            and PolicyReasonCode.EVIDENCE_UNAVAILABLE not in generated_reasons
        ):
            _raise(
                ExplanationValidationFailureCode.UNKNOWN_MISSING_EVIDENCE
            )


        if generated_reasons - required_reason_set:
            _raise(ExplanationValidationFailureCode.UNSUPPORTED_REASON)
        if required_reason_set - generated_reasons:
            _raise(ExplanationValidationFailureCode.MISSING_REQUIRED_REASON)
        if generated_actions - required_action_set:
            _raise(ExplanationValidationFailureCode.UNSUPPORTED_ACTION)
        if required_action_set - generated_actions:
            _raise(ExplanationValidationFailureCode.MISSING_REQUIRED_ACTION)

        return required_claims
