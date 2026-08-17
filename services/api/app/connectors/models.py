from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
GitHubRepositoryIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]
CommitSha = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[0-9a-fA-F]{40}([0-9a-fA-F]{24})?$",
    ),
]


JiraIssueKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[A-Z][A-Z0-9]*-[1-9][0-9]*$",
    ),
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PullRequestState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"


class Mergeability(StrEnum):
    MERGEABLE = "mergeable"
    CONFLICTING = "conflicting"
    UNKNOWN = "unknown"


class CheckStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class JiraIssueStatus(StrEnum):
    TO_DO = "to_do"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class BlockerState(StrEnum):
    BLOCKED = "blocked"
    NOT_BLOCKED = "not_blocked"
    UNKNOWN = "unknown"


class ConnectorSource(StrEnum):
    FAKE = "fake"
    LIVE = "live"


class ConnectorRequest(ContractModel):
    repository_owner: NonEmptyString
    repository_name: NonEmptyString
    pr_number: Annotated[int, Field(strict=True, gt=0)]


class GitHubCommitEvidenceRequest(ContractModel):
    repository_owner: GitHubRepositoryIdentifier
    repository_name: GitHubRepositoryIdentifier
    commit_sha: CommitSha


class GitHubPullRequestEvidenceRequest(ContractModel):
    repository_owner: GitHubRepositoryIdentifier
    repository_name: GitHubRepositoryIdentifier
    pr_number: Annotated[int, Field(strict=True, gt=0)]


class GitHubUser(ContractModel):
    login: NonEmptyString


class RequiredCheck(ContractModel):
    name: NonEmptyString
    status: CheckStatus


class GitHubPullRequest(ContractModel):
    pr_number: Annotated[int, Field(strict=True, gt=0)]
    title: NonEmptyString
    url: NonEmptyString
    head_branch: NonEmptyString
    base_branch: NonEmptyString
    state: PullRequestState
    is_draft: bool
    mergeability: Mergeability
    required_checks: tuple[RequiredCheck, ...]
    required_checks_known: bool
    approvals: tuple[GitHubUser, ...]
    required_approval_count: Annotated[int, Field(strict=True, ge=0)] | None
    reviews_known: bool
    changes_requested: bool
    author: GitHubUser
    assignees: tuple[GitHubUser, ...]
    requested_reviewers: tuple[GitHubUser, ...]
    linked_jira_key: JiraIssueKey | None


    @model_validator(mode="after")
    def validate_evidence_availability(self) -> Self:
        if not self.required_checks_known and self.required_checks:
            raise ValueError("unknown required checks cannot contain check facts")
        if not self.reviews_known and (self.approvals or self.changes_requested):
            raise ValueError("unknown reviews cannot contain review conclusions")
        return self


class JiraAssignee(ContractModel):
    account_id: NonEmptyString
    display_name: NonEmptyString


class JiraIssue(ContractModel):
    issue_key: JiraIssueKey
    status: JiraIssueStatus
    blocker_state: BlockerState
    assignee: JiraAssignee | None
    status_id: NonEmptyString | None = None
    status_name: NonEmptyString | None = None
    is_resolved: bool | None = None
