from app.explanations.models import (
    MergeReadinessExplanation,
    ValidatedExplanation,
)
from app.policy import MergeReadinessDecision, PendingActionCode, PolicyReasonCode


SUMMARY_BY_DECISION: dict[MergeReadinessDecision, str] = {
    MergeReadinessDecision.READY: (
        "The deterministic policy found the pull request ready."
    ),
    MergeReadinessDecision.BLOCKED: (
        "The deterministic policy found verified merge blockers."
    ),
    MergeReadinessDecision.UNKNOWN: (
        "The deterministic policy needs required evidence."
    ),
}

REASON_TEXT_BY_CODE: dict[PolicyReasonCode, str] = {
    PolicyReasonCode.READY: "All required merge-readiness evidence is satisfied.",
    PolicyReasonCode.PR_IS_DRAFT: "The pull request is still a draft.",
    PolicyReasonCode.PR_CLOSED_UNMERGED: (
        "The pull request is closed without being merged."
    ),
    PolicyReasonCode.MERGE_CONFLICT: "The pull request has a merge conflict.",
    PolicyReasonCode.CI_CHECK_FAILED: "A required CI check failed.",
    PolicyReasonCode.CI_CHECK_PENDING: "A required CI check is still pending.",
    PolicyReasonCode.APPROVAL_MISSING: "A required approval is missing.",
    PolicyReasonCode.CHANGES_REQUESTED: (
        "A reviewer has requested changes that remain unresolved."
    ),
    PolicyReasonCode.JIRA_LINK_MISSING: (
        "The pull request does not contain a linked Jira issue."
    ),
    PolicyReasonCode.JIRA_NOT_COMPLETE: "The linked Jira issue is not complete.",
    PolicyReasonCode.JIRA_BLOCKER_PRESENT: (
        "The linked Jira issue has a verified blocker."
    ),
    PolicyReasonCode.EVIDENCE_UNAVAILABLE: (
        "Required merge-readiness evidence is unavailable."
    ),
}

ACTION_TEXT_BY_CODE: dict[PendingActionCode, str] = {
    PendingActionCode.MARK_PR_READY: "Mark the pull request as ready for review.",
    PendingActionCode.REOPEN_PR: "Reopen the pull request before merging.",
    PendingActionCode.RESOLVE_MERGE_CONFLICT: (
        "Resolve the merge conflict and refresh the analysis."
    ),
    PendingActionCode.FIX_CI_CHECK: "Fix the failed required CI check.",
    PendingActionCode.WAIT_FOR_CI_CHECK: (
        "Wait for the pending required CI check to finish."
    ),
    PendingActionCode.GET_REQUIRED_APPROVAL: (
        "Obtain the missing required approval."
    ),
    PendingActionCode.ADDRESS_REQUESTED_CHANGES: (
        "Address the reviewer's requested changes."
    ),
    PendingActionCode.LINK_JIRA_ISSUE: (
        "Link the required Jira issue to the pull request."
    ),
    PendingActionCode.COMPLETE_JIRA_ISSUE: (
        "Move the linked Jira issue to a completed status."
    ),
    PendingActionCode.CLEAR_JIRA_BLOCKER: (
        "Clear the verified blocker on the linked Jira issue."
    ),
    PendingActionCode.RETRY_EVIDENCE: (
        "Retry the analysis when the required evidence is available."
    ),
}


def render_validated_explanation(
    validated: ValidatedExplanation,
) -> MergeReadinessExplanation:
    return MergeReadinessExplanation(
        decision=validated.decision,
        summary=SUMMARY_BY_DECISION[validated.decision],
        reasons=tuple(
            REASON_TEXT_BY_CODE[code] for code in validated.reason_codes
        ),
        recommended_actions=tuple(
            ACTION_TEXT_BY_CODE[code]
            for code in validated.action_codes
        ),
    )
