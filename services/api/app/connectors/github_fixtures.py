pass

from types import MappingProxyType
from typing import Any

from app.connectors.fixture_catalog import (
    CHANGES_REQUESTED_REQUEST,
    DRAFT_REQUEST,
    FAILED_CI_REQUEST,
    JIRA_IN_PROGRESS_REQUEST,
    MERGE_CONFLICT_REQUEST,
    MERGE_READY_REQUEST,
    MISSING_APPROVAL_REQUEST,
    PENDING_CI_REQUEST,
)
from app.connectors.models import (
    CheckStatus,
    ConnectorRequest,
    GitHubPullRequest,
    GitHubUser,
    Mergeability,
    PullRequestState,
    RequiredCheck,
)




_AUTHOR = GitHubUser(login="octo-author")
_ASSIGNEE = GitHubUser(login="octo-assignee")
_REVIEWER = GitHubUser(login="octo-reviewer")
_PASSING_CHECKS = (
    RequiredCheck(name="unit-tests", status=CheckStatus.PASSED),
    RequiredCheck(name="type-check", status=CheckStatus.PASSED),
)


_BASE_GITHUB_FIXTURE = GitHubPullRequest(
    pr_number=101,
    title="ENG-101 Prepare analytics service",
    url="https://github.example/acme/analytics/pull/101",
    head_branch="feature/ENG-101",
    base_branch="main",
    state=PullRequestState.OPEN,
    is_draft=False,
    mergeability=Mergeability.MERGEABLE,
    required_checks=_PASSING_CHECKS,
    required_checks_known=True,
    approvals=(_REVIEWER,),
    required_approval_count=1,
    reviews_known=True,
    changes_requested=False,
    author=_AUTHOR,
    assignees=(_ASSIGNEE,),
    requested_reviewers=(),
    linked_jira_key="ENG-101",
)


def _github_fixture(**updates: Any) -> GitHubPullRequest:
    pass

    fixture_data = _BASE_GITHUB_FIXTURE.model_dump()
    fixture_data.update(updates)
    return GitHubPullRequest.model_validate(fixture_data)




GITHUB_FIXTURES = MappingProxyType(
    {
        MERGE_READY_REQUEST: _BASE_GITHUB_FIXTURE,
        DRAFT_REQUEST: _github_fixture(
            pr_number=102,
            title="ENG-102 Draft analytics change",
            url="https://github.example/acme/draft-service/pull/102",
            head_branch="feature/ENG-102",
            is_draft=True,
            linked_jira_key="ENG-102",
        ),
        FAILED_CI_REQUEST: _github_fixture(
            pr_number=103,
            title="ENG-103 Failed CI example",
            url="https://github.example/acme/failed-ci-service/pull/103",
            head_branch="feature/ENG-103",
            required_checks=(
                RequiredCheck(name="unit-tests", status=CheckStatus.FAILED),
                RequiredCheck(name="type-check", status=CheckStatus.PASSED),
            ),
            linked_jira_key="ENG-103",
        ),
        PENDING_CI_REQUEST: _github_fixture(
            pr_number=104,
            title="ENG-104 Pending CI example",
            url="https://github.example/acme/pending-ci-service/pull/104",
            head_branch="feature/ENG-104",
            required_checks=(
                RequiredCheck(name="unit-tests", status=CheckStatus.PENDING),
                RequiredCheck(name="type-check", status=CheckStatus.PASSED),
            ),
            linked_jira_key="ENG-104",
        ),
        MISSING_APPROVAL_REQUEST: _github_fixture(
            pr_number=105,
            title="ENG-105 Missing approval example",
            url="https://github.example/acme/missing-approval-service/pull/105",
            head_branch="feature/ENG-105",
            approvals=(),
            linked_jira_key="ENG-105",
        ),
        CHANGES_REQUESTED_REQUEST: _github_fixture(
            pr_number=106,
            title="ENG-106 Changes requested example",
            url="https://github.example/acme/changes-requested-service/pull/106",
            head_branch="feature/ENG-106",
            approvals=(),
            changes_requested=True,
            linked_jira_key="ENG-106",
        ),
        MERGE_CONFLICT_REQUEST: _github_fixture(
            pr_number=107,
            title="ENG-107 Merge conflict example",
            url="https://github.example/acme/merge-conflict-service/pull/107",
            head_branch="feature/ENG-107",
            mergeability=Mergeability.CONFLICTING,
            linked_jira_key="ENG-107",
        ),
        JIRA_IN_PROGRESS_REQUEST: _github_fixture(
            pr_number=108,
            title="ENG-108 Jira in progress example",
            url="https://github.example/acme/jira-in-progress-service/pull/108",
            head_branch="feature/ENG-108",
            linked_jira_key="ENG-108",
        ),
    }
)
