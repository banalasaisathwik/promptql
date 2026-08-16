from app.connectors.models import (
    BlockerState,
    CheckStatus,
    GitHubPullRequest,
    JiraIssue,
    JiraIssueStatus,
    Mergeability,
    PullRequestState,
)
from app.policy.models import (
    EvidenceReference,
    EvidenceSource,
    MergeReadinessDecision,
    MergeReadinessResult,
    PendingAction,
    PendingActionCode,
    PolicyFinding,
    PolicyReasonCode,
)


def _record_evidence(
    evidence_references: list[EvidenceReference],
    source: EvidenceSource,
    field: str,
    value: str | bool | int | None,
) -> str:
    reference_id = f"{source.value}.{field}"
    evidence_references.append(
        EvidenceReference(
            reference_id=reference_id,
            source=source,
            field=field,
            value=value,
        )
    )
    return reference_id


def _add_blocker(
    blockers: list[PolicyFinding],
    pending_actions: list[PendingAction],
    reason_code: PolicyReasonCode,
    blocker_message: str,
    evidence_reference_ids: tuple[str, ...],
    action_code: PendingActionCode,
    action_message: str,
) -> None:
    blockers.append(
        PolicyFinding(
            reason_code=reason_code,
            message=blocker_message,
            evidence_reference_ids=evidence_reference_ids,
        )
    )
    pending_actions.append(
        PendingAction(
            action_code=action_code,
            reason_code=reason_code,
            message=action_message,
        )
    )


def _add_missing_information(
    missing_information: list[PolicyFinding],
    pending_actions: list[PendingAction],
    message: str,
    evidence_reference_ids: tuple[str, ...] = (),
) -> None:
    missing_information.append(
        PolicyFinding(
            reason_code=PolicyReasonCode.EVIDENCE_UNAVAILABLE,
            message=message,
            evidence_reference_ids=evidence_reference_ids,
        )
    )
    pending_actions.append(
        PendingAction(
            action_code=PendingActionCode.RETRY_EVIDENCE,
            reason_code=PolicyReasonCode.EVIDENCE_UNAVAILABLE,
            message="Retrieve the required evidence and evaluate the policy again.",
        )
    )


def evaluate_merge_readiness(
    github: GitHubPullRequest | None,
    jira: JiraIssue | None,
) -> MergeReadinessResult:
    blockers: list[PolicyFinding] = []
    pending_actions: list[PendingAction] = []
    missing_information: list[PolicyFinding] = []
    evidence_references: list[EvidenceReference] = []


    if github is None:
        _add_missing_information(
            missing_information,
            pending_actions,
            "GitHub pull-request evidence is unavailable.",
        )
        if jira is None:
            _add_missing_information(
                missing_information,
                pending_actions,
                "Jira issue evidence is unavailable.",
            )
    else:
        state_reference = _record_evidence(
            evidence_references,
            EvidenceSource.GITHUB,
            "state",
            github.state.value,
        )
        draft_reference = _record_evidence(
            evidence_references,
            EvidenceSource.GITHUB,
            "is_draft",
            github.is_draft,
        )
        mergeability_reference = _record_evidence(
            evidence_references,
            EvidenceSource.GITHUB,
            "mergeability",
            github.mergeability.value,
        )
        approval_reference = _record_evidence(
            evidence_references,
            EvidenceSource.GITHUB,
            "approvals.count",
            len(github.approvals),
        )
        approval_requirement_reference = _record_evidence(
            evidence_references,
            EvidenceSource.GITHUB,
            "required_approval_count",
            github.required_approval_count,
        )
        reviews_known_reference = _record_evidence(
            evidence_references,
            EvidenceSource.GITHUB,
            "reviews_known",
            github.reviews_known,
        )
        changes_reference = _record_evidence(
            evidence_references,
            EvidenceSource.GITHUB,
            "changes_requested",
            github.changes_requested,
        )
        jira_link_reference = _record_evidence(
            evidence_references,
            EvidenceSource.GITHUB,
            "linked_jira_key",
            github.linked_jira_key,
        )

        checks_known_reference = _record_evidence(
            evidence_references,
            EvidenceSource.GITHUB,
            "required_checks_known",
            github.required_checks_known,
        )
        check_references: list[tuple[str, str]] = []
        for check_index, check in enumerate(github.required_checks):
            check_name_reference = _record_evidence(
                evidence_references,
                EvidenceSource.GITHUB,
                f"required_checks[{check_index}].name",
                check.name,
            )
            check_status_reference = _record_evidence(
                evidence_references,
                EvidenceSource.GITHUB,
                f"required_checks[{check_index}].status",
                check.status.value,
            )
            check_references.append((check_name_reference, check_status_reference))


        if github.is_draft:
            _add_blocker(
                blockers,
                pending_actions,
                PolicyReasonCode.PR_IS_DRAFT,
                "The pull request is a draft.",
                (draft_reference,),
                PendingActionCode.MARK_PR_READY,
                "Mark the pull request ready for review.",
            )

        if github.state is PullRequestState.CLOSED:
            _add_blocker(
                blockers,
                pending_actions,
                PolicyReasonCode.PR_CLOSED_UNMERGED,
                "The pull request is closed without being merged.",
                (state_reference,),
                PendingActionCode.REOPEN_PR,
                "Reopen the pull request before merging.",
            )

        if github.mergeability is Mergeability.CONFLICTING:
            _add_blocker(
                blockers,
                pending_actions,
                PolicyReasonCode.MERGE_CONFLICT,
                "The pull request has a merge conflict.",
                (mergeability_reference,),
                PendingActionCode.RESOLVE_MERGE_CONFLICT,
                "Resolve the merge conflict.",
            )
        elif github.mergeability is Mergeability.UNKNOWN:
            _add_missing_information(
                missing_information,
                pending_actions,
                "GitHub has not determined mergeability.",
                (mergeability_reference,),
            )


        if not github.required_checks_known:
            _add_missing_information(
                missing_information,
                pending_actions,
                "GitHub required-check rules are unavailable.",
                (checks_known_reference,),
            )
        else:
            for expected_status, reason_code, action_code in (
                (
                    CheckStatus.FAILED,
                    PolicyReasonCode.CI_CHECK_FAILED,
                    PendingActionCode.FIX_CI_CHECK,
                ),
                (
                    CheckStatus.PENDING,
                    PolicyReasonCode.CI_CHECK_PENDING,
                    PendingActionCode.WAIT_FOR_CI_CHECK,
                ),
            ):
                for check_index, check in enumerate(github.required_checks):
                    if check.status is not expected_status:
                        continue
                    check_evidence = check_references[check_index]
                    if check.status is CheckStatus.FAILED:
                        action_message = f"Fix required CI check '{check.name}'."
                    else:
                        action_message = (
                            f"Wait for required CI check '{check.name}' to finish."
                        )
                    _add_blocker(
                        blockers,
                        pending_actions,
                        reason_code,
                        f"Required CI check '{check.name}' is {check.status.value}.",
                        check_evidence,
                        action_code,
                        action_message,
                    )


        if not github.reviews_known:
            _add_missing_information(
                missing_information,
                pending_actions,
                "GitHub review evidence is unavailable.",
                (reviews_known_reference,),
            )
        elif github.required_approval_count is None:
            _add_missing_information(
                missing_information,
                pending_actions,
                "GitHub required-approval rules are unavailable.",
                (approval_requirement_reference,),
            )
        elif len(github.approvals) < github.required_approval_count:
            _add_blocker(
                blockers,
                pending_actions,
                PolicyReasonCode.APPROVAL_MISSING,
                "The pull request does not have the required approval count.",
                (approval_reference, approval_requirement_reference),
                PendingActionCode.GET_REQUIRED_APPROVAL,
                (
                    "Obtain the remaining approvals required by GitHub rules."
                ),
            )

        if github.reviews_known and github.changes_requested:
            _add_blocker(
                blockers,
                pending_actions,
                PolicyReasonCode.CHANGES_REQUESTED,
                "A reviewer has requested changes.",
                (changes_reference,),
                PendingActionCode.ADDRESS_REQUESTED_CHANGES,
                "Address the requested changes and obtain a new review.",
            )


        if github.linked_jira_key is None:
            _add_blocker(
                blockers,
                pending_actions,
                PolicyReasonCode.JIRA_LINK_MISSING,
                "The pull request has no linked Jira issue.",
                (jira_link_reference,),
                PendingActionCode.LINK_JIRA_ISSUE,
                "Link a Jira issue to the pull request.",
            )
        elif jira is None:
            _add_missing_information(
                missing_information,
                pending_actions,
                "Jira issue evidence is unavailable.",
            )
        else:
            jira_key_reference = _record_evidence(
                evidence_references,
                EvidenceSource.JIRA,
                "issue_key",
                jira.issue_key,
            )


            if jira.issue_key != github.linked_jira_key:
                _add_missing_information(
                    missing_information,
                    pending_actions,
                    "Jira evidence does not match the issue linked by GitHub.",
                    (jira_link_reference, jira_key_reference),
                )
            else:
                jira_status_reference = _record_evidence(
                    evidence_references,
                    EvidenceSource.JIRA,
                    "status_category",
                    jira.status.value,
                )
                if jira.status_name is not None:
                    _record_evidence(
                        evidence_references,
                        EvidenceSource.JIRA,
                        "status_name",
                        jira.status_name,
                    )
                jira_blocker_reference = _record_evidence(
                    evidence_references,
                    EvidenceSource.JIRA,
                    "blocker_state",
                    jira.blocker_state.value,
                )


                if jira.status is not JiraIssueStatus.DONE:
                    _add_blocker(
                        blockers,
                        pending_actions,
                        PolicyReasonCode.JIRA_NOT_COMPLETE,
                        "The linked Jira issue is not complete.",
                        (jira_key_reference, jira_status_reference),
                        PendingActionCode.COMPLETE_JIRA_ISSUE,
                        "Move the linked Jira issue to done.",
                    )

                if jira.blocker_state is BlockerState.BLOCKED:
                    _add_blocker(
                        blockers,
                        pending_actions,
                        PolicyReasonCode.JIRA_BLOCKER_PRESENT,
                        "The linked Jira issue has a blocker.",
                        (jira_key_reference, jira_blocker_reference),
                        PendingActionCode.CLEAR_JIRA_BLOCKER,
                        "Clear the blocker on the linked Jira issue.",
                    )


    if blockers:
        decision = MergeReadinessDecision.BLOCKED
        reason_code = blockers[0].reason_code
        summary = f"{len(blockers)} verified blocker(s) prevent merge readiness."
    elif missing_information:
        decision = MergeReadinessDecision.UNKNOWN
        reason_code = PolicyReasonCode.EVIDENCE_UNAVAILABLE
        summary = "Required evidence is unavailable or indeterminate."
    else:
        decision = MergeReadinessDecision.READY
        reason_code = PolicyReasonCode.READY
        summary = "All required V1 merge-readiness conditions are satisfied."

    return MergeReadinessResult(
        decision=decision,
        summary=summary,
        reason_code=reason_code,
        blockers=tuple(blockers),
        pending_actions=tuple(pending_actions),
        missing_information=tuple(missing_information),
        evidence_references=tuple(evidence_references),
    )
