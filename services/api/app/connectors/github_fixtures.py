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
    state=PullRequestState.OPEN,
    is_draft=False,
    mergeability=Mergeability.MERGEABLE,
    required_checks=_PASSING_CHECKS,
    approvals=(_REVIEWER,),
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
            is_draft=True,
            linked_jira_key="ENG-102",
        ),
        FAILED_CI_REQUEST: _github_fixture(
            required_checks=(
                RequiredCheck(name="unit-tests", status=CheckStatus.FAILED),
                RequiredCheck(name="type-check", status=CheckStatus.PASSED),
            ),
            linked_jira_key="ENG-103",
        ),
        PENDING_CI_REQUEST: _github_fixture(
            required_checks=(
                RequiredCheck(name="unit-tests", status=CheckStatus.PENDING),
                RequiredCheck(name="type-check", status=CheckStatus.PASSED),
            ),
            linked_jira_key="ENG-104",
        ),
        MISSING_APPROVAL_REQUEST: _github_fixture(
            approvals=(),
            linked_jira_key="ENG-105",
        ),
        CHANGES_REQUESTED_REQUEST: _github_fixture(
            approvals=(),
            changes_requested=True,
            linked_jira_key="ENG-106",
        ),
        MERGE_CONFLICT_REQUEST: _github_fixture(
            mergeability=Mergeability.CONFLICTING,
            linked_jira_key="ENG-107",
        ),
        JIRA_IN_PROGRESS_REQUEST: _github_fixture(linked_jira_key="ENG-108"),
    }
)
