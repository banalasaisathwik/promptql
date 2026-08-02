pass

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

                                                                          
                                                                               
NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

                                                                                
                                                                                
                                                                               
JiraIssueKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[A-Z][A-Z0-9]*-[1-9][0-9]*$",
    ),
]


class ContractModel(BaseModel):
    pass

    model_config = ConfigDict(extra="forbid", frozen=True)


class PullRequestState(StrEnum):
    pass

    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"


class Mergeability(StrEnum):
    pass

    MERGEABLE = "mergeable"
    CONFLICTING = "conflicting"
    UNKNOWN = "unknown"


class CheckStatus(StrEnum):
    pass

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class JiraIssueStatus(StrEnum):
    pass

    TO_DO = "to_do"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class BlockerState(StrEnum):
    pass

    BLOCKED = "blocked"
    NOT_BLOCKED = "not_blocked"


class ConnectorRequest(ContractModel):
    pass

    repository_owner: NonEmptyString
    repository_name: NonEmptyString
    pr_number: Annotated[int, Field(strict=True, gt=0)]


class GitHubUser(ContractModel):
    pass

    login: NonEmptyString


class RequiredCheck(ContractModel):
    pass

    name: NonEmptyString
    status: CheckStatus


class GitHubPullRequest(ContractModel):
    pass

    state: PullRequestState
    is_draft: bool
    mergeability: Mergeability
    required_checks: tuple[RequiredCheck, ...]
    approvals: tuple[GitHubUser, ...]
    changes_requested: bool
    author: GitHubUser
    assignees: tuple[GitHubUser, ...]
    requested_reviewers: tuple[GitHubUser, ...]
    linked_jira_key: JiraIssueKey | None


class JiraAssignee(ContractModel):
    pass

    account_id: NonEmptyString
    display_name: NonEmptyString


class JiraIssue(ContractModel):
    pass

    issue_key: JiraIssueKey
    status: JiraIssueStatus
    blocker_state: BlockerState
    assignee: JiraAssignee | None
