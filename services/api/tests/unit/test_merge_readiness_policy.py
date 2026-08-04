pass

import asyncio
import unittest
from typing import Any

from app.connectors.fakes import FakeGitHubConnector, FakeJiraConnector
from app.connectors.fixture_catalog import MERGE_READY_REQUEST
from app.connectors.models import (
    BlockerState,
    CheckStatus,
    GitHubPullRequest,
    JiraIssue,
    JiraIssueStatus,
    Mergeability,
    PullRequestState,
    RequiredCheck,
)
from app.policy import (
    MergeReadinessDecision,
    PolicyReasonCode,
    evaluate_merge_readiness,
)


def _ready_facts() -> tuple[GitHubPullRequest, JiraIssue]:
    pass

    github = asyncio.run(
        FakeGitHubConnector().get_pull_request(MERGE_READY_REQUEST)
    )
    jira = asyncio.run(FakeJiraConnector().get_issue(github.linked_jira_key))
    return github, jira


def _github_with(**updates: Any) -> GitHubPullRequest:
    pass

    github, _ = _ready_facts()
    values = github.model_dump()
    values.update(updates)
    return GitHubPullRequest.model_validate(values)


def _jira_with(**updates: Any) -> JiraIssue:
    pass

    _, jira = _ready_facts()
    values = jira.model_dump()
    values.update(updates)
    return JiraIssue.model_validate(values)


class MergeReadinessPolicyTests(unittest.TestCase):
    def test_merge_ready_fixture_is_ready(self) -> None:
        github, jira = _ready_facts()

        result = evaluate_merge_readiness(github, jira)

        self.assertEqual(result.decision, MergeReadinessDecision.READY)
        self.assertEqual(result.reason_code, PolicyReasonCode.READY)
        self.assertEqual(result.blockers, ())
        self.assertEqual(result.missing_information, ())

    def test_every_individual_blocker_is_detected(self) -> None:
        github, jira = _ready_facts()
        cases = (
            (
                "draft PR",
                _github_with(is_draft=True),
                jira,
                PolicyReasonCode.PR_IS_DRAFT,
            ),
            (
                "closed unmerged PR",
                _github_with(state=PullRequestState.CLOSED),
                jira,
                PolicyReasonCode.PR_CLOSED_UNMERGED,
            ),
            (
                "merge conflict",
                _github_with(mergeability=Mergeability.CONFLICTING),
                jira,
                PolicyReasonCode.MERGE_CONFLICT,
            ),
            (
                "failed CI",
                _github_with(
                    required_checks=(
                        RequiredCheck(name="unit-tests", status=CheckStatus.FAILED),
                    )
                ),
                jira,
                PolicyReasonCode.CI_CHECK_FAILED,
            ),
            (
                "pending CI",
                _github_with(
                    required_checks=(
                        RequiredCheck(name="unit-tests", status=CheckStatus.PENDING),
                    )
                ),
                jira,
                PolicyReasonCode.CI_CHECK_PENDING,
            ),
            (
                "missing approval",
                _github_with(approvals=()),
                jira,
                PolicyReasonCode.APPROVAL_MISSING,
            ),
            (
                "changes requested",
                _github_with(changes_requested=True),
                jira,
                PolicyReasonCode.CHANGES_REQUESTED,
            ),
            (
                "missing Jira link",
                _github_with(linked_jira_key=None),
                None,
                PolicyReasonCode.JIRA_LINK_MISSING,
            ),
            (
                "Jira not complete",
                github,
                _jira_with(status=JiraIssueStatus.IN_PROGRESS),
                PolicyReasonCode.JIRA_NOT_COMPLETE,
            ),
            (
                "Jira blocker present",
                github,
                _jira_with(blocker_state=BlockerState.BLOCKED),
                PolicyReasonCode.JIRA_BLOCKER_PRESENT,
            ),
        )

        for name, github_facts, jira_facts, expected_reason in cases:
            with self.subTest(name=name):
                result = evaluate_merge_readiness(github_facts, jira_facts)

                self.assertEqual(result.decision, MergeReadinessDecision.BLOCKED)
                self.assertEqual(
                    tuple(blocker.reason_code for blocker in result.blockers),
                    (expected_reason,),
                )

    def test_multiple_simultaneous_blockers_are_all_preserved(self) -> None:
        github = _github_with(
            is_draft=True,
            mergeability=Mergeability.CONFLICTING,
            approvals=(),
            changes_requested=True,
        )
        jira = _jira_with(
            status=JiraIssueStatus.IN_PROGRESS,
            blocker_state=BlockerState.BLOCKED,
        )

        result = evaluate_merge_readiness(github, jira)

        self.assertEqual(result.decision, MergeReadinessDecision.BLOCKED)
        self.assertEqual(
            tuple(blocker.reason_code for blocker in result.blockers),
            (
                PolicyReasonCode.PR_IS_DRAFT,
                PolicyReasonCode.MERGE_CONFLICT,
                PolicyReasonCode.APPROVAL_MISSING,
                PolicyReasonCode.CHANGES_REQUESTED,
                PolicyReasonCode.JIRA_NOT_COMPLETE,
                PolicyReasonCode.JIRA_BLOCKER_PRESENT,
            ),
        )

    def test_unavailable_github_evidence_is_unknown(self) -> None:
        _, jira = _ready_facts()

        result = evaluate_merge_readiness(None, jira)

        self.assertEqual(result.decision, MergeReadinessDecision.UNKNOWN)
        self.assertEqual(result.reason_code, PolicyReasonCode.EVIDENCE_UNAVAILABLE)
        self.assertEqual(result.blockers, ())

    def test_unavailable_jira_evidence_is_unknown(self) -> None:
        github, _ = _ready_facts()

        result = evaluate_merge_readiness(github, None)

        self.assertEqual(result.decision, MergeReadinessDecision.UNKNOWN)
        self.assertEqual(result.reason_code, PolicyReasonCode.EVIDENCE_UNAVAILABLE)
        self.assertEqual(result.blockers, ())

    def test_unknown_jira_blocker_evidence_is_unknown_when_status_is_done(self) -> None:
        github, _ = _ready_facts()

        result = evaluate_merge_readiness(
            github,
            _jira_with(blocker_state=BlockerState.UNKNOWN),
        )

        self.assertEqual(result.decision, MergeReadinessDecision.UNKNOWN)
        self.assertIn(
            "Jira blocker evidence is unavailable.",
            {information.message for information in result.missing_information},
        )

    def test_verified_incomplete_jira_wins_over_unknown_blocker_evidence(self) -> None:
        github, _ = _ready_facts()

        result = evaluate_merge_readiness(
            github,
            _jira_with(
                status=JiraIssueStatus.IN_PROGRESS,
                blocker_state=BlockerState.UNKNOWN,
            ),
        )

        self.assertEqual(result.decision, MergeReadinessDecision.BLOCKED)
        self.assertIn(
            PolicyReasonCode.JIRA_NOT_COMPLETE,
            {blocker.reason_code for blocker in result.blockers},
        )

    def test_indeterminate_mergeability_is_unknown(self) -> None:
        github = _github_with(mergeability=Mergeability.UNKNOWN)
        _, jira = _ready_facts()

        result = evaluate_merge_readiness(github, jira)

        self.assertEqual(result.decision, MergeReadinessDecision.UNKNOWN)
        self.assertEqual(result.reason_code, PolicyReasonCode.EVIDENCE_UNAVAILABLE)
        self.assertEqual(result.blockers, ())
        self.assertEqual(len(result.missing_information), 1)
        self.assertEqual(
            result.missing_information[0].evidence_reference_ids,
            ("github.mergeability",),
        )

    def test_jira_evidence_for_a_different_issue_is_unknown(self) -> None:
        github, _ = _ready_facts()
        unrelated_jira = _jira_with(issue_key="ENG-999")

        result = evaluate_merge_readiness(github, unrelated_jira)

        self.assertEqual(result.decision, MergeReadinessDecision.UNKNOWN)
        self.assertEqual(result.blockers, ())
        self.assertEqual(
            result.missing_information[0].evidence_reference_ids,
            ("github.linked_jira_key", "jira.issue_key"),
        )

    def test_unknown_github_requirements_do_not_create_blockers(self) -> None:
        _, jira = _ready_facts()
        github = _github_with(
            required_checks=(),
            required_checks_known=False,
            required_approval_count=None,
        )

        result = evaluate_merge_readiness(github, jira)

        self.assertEqual(result.decision, MergeReadinessDecision.UNKNOWN)
        self.assertEqual(result.blockers, ())
        self.assertTrue(
            all(
                finding.reason_code is PolicyReasonCode.EVIDENCE_UNAVAILABLE
                for finding in result.missing_information
            )
        )

    def test_verified_blocker_wins_over_unknown_github_requirements(self) -> None:
        _, jira = _ready_facts()
        github = _github_with(
            is_draft=True,
            required_checks=(),
            required_checks_known=False,
            required_approval_count=None,
        )

        result = evaluate_merge_readiness(github, jira)

        self.assertEqual(result.decision, MergeReadinessDecision.BLOCKED)
        self.assertIn(
            PolicyReasonCode.PR_IS_DRAFT,
            {blocker.reason_code for blocker in result.blockers},
        )
        self.assertTrue(result.missing_information)

    def test_verified_blocker_takes_precedence_over_unavailable_evidence(self) -> None:
        github = _github_with(is_draft=True)

        result = evaluate_merge_readiness(github, None)

        self.assertEqual(result.decision, MergeReadinessDecision.BLOCKED)
        self.assertEqual(result.reason_code, PolicyReasonCode.PR_IS_DRAFT)
        self.assertEqual(len(result.blockers), 1)
        self.assertEqual(len(result.missing_information), 1)

    def test_identical_input_produces_identical_output(self) -> None:
        github, jira = _ready_facts()

        first_result = evaluate_merge_readiness(github, jira)
        second_result = evaluate_merge_readiness(github, jira)

        self.assertEqual(first_result, second_result)
        self.assertEqual(first_result.model_dump(), second_result.model_dump())

    def test_every_blocker_claim_points_to_observed_input_evidence(self) -> None:
        github = _github_with(
            is_draft=True,
            required_checks=(
                RequiredCheck(name="unit-tests", status=CheckStatus.FAILED),
            ),
            approvals=(),
        )
        _, jira = _ready_facts()

        result = evaluate_merge_readiness(github, jira)
        evidence_by_id = {
            reference.reference_id: reference.value
            for reference in result.evidence_references
        }

        for blocker in result.blockers:
            self.assertTrue(blocker.evidence_reference_ids)
            for reference_id in blocker.evidence_reference_ids:
                self.assertIn(reference_id, evidence_by_id)

        self.assertEqual(evidence_by_id["github.is_draft"], True)
        self.assertEqual(
            evidence_by_id["github.required_checks[0].status"],
            CheckStatus.FAILED.value,
        )
        self.assertEqual(evidence_by_id["github.approvals.count"], 0)


if __name__ == "__main__":
    unittest.main()
