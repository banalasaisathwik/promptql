pass

from enum import StrEnum

from app.connectors.models import ContractModel, NonEmptyString


class MergeReadinessDecision(StrEnum):
    pass

    READY = "ready"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class PolicyReasonCode(StrEnum):
    pass

    READY = "ready"
    PR_IS_DRAFT = "pr_is_draft"
    PR_CLOSED_UNMERGED = "pr_closed_unmerged"
    MERGE_CONFLICT = "merge_conflict"
    CI_CHECK_FAILED = "ci_check_failed"
    CI_CHECK_PENDING = "ci_check_pending"
    APPROVAL_MISSING = "approval_missing"
    CHANGES_REQUESTED = "changes_requested"
    JIRA_LINK_MISSING = "jira_link_missing"
    JIRA_NOT_COMPLETE = "jira_not_complete"
    JIRA_BLOCKER_PRESENT = "jira_blocker_present"
    EVIDENCE_UNAVAILABLE = "evidence_unavailable"


class PendingActionCode(StrEnum):
    pass

    MARK_PR_READY = "mark_pr_ready"
    REOPEN_PR = "reopen_pr"
    RESOLVE_MERGE_CONFLICT = "resolve_merge_conflict"
    FIX_CI_CHECK = "fix_ci_check"
    WAIT_FOR_CI_CHECK = "wait_for_ci_check"
    GET_REQUIRED_APPROVAL = "get_required_approval"
    ADDRESS_REQUESTED_CHANGES = "address_requested_changes"
    LINK_JIRA_ISSUE = "link_jira_issue"
    COMPLETE_JIRA_ISSUE = "complete_jira_issue"
    CLEAR_JIRA_BLOCKER = "clear_jira_blocker"
    RETRY_EVIDENCE = "retry_evidence"


class EvidenceSource(StrEnum):
    pass

    GITHUB = "github"
    JIRA = "jira"


class EvidenceReference(ContractModel):
    pass

    reference_id: NonEmptyString
    source: EvidenceSource
    field: NonEmptyString
    value: str | bool | int | None


class PolicyFinding(ContractModel):
    pass

    reason_code: PolicyReasonCode
    message: NonEmptyString
    evidence_reference_ids: tuple[NonEmptyString, ...]


class PendingAction(ContractModel):
    pass

    action_code: PendingActionCode
    reason_code: PolicyReasonCode
    message: NonEmptyString


class MergeReadinessResult(ContractModel):
    pass

    decision: MergeReadinessDecision
    summary: NonEmptyString
    reason_code: PolicyReasonCode
    blockers: tuple[PolicyFinding, ...]
    pending_actions: tuple[PendingAction, ...]
    missing_information: tuple[PolicyFinding, ...]
    evidence_references: tuple[EvidenceReference, ...]
