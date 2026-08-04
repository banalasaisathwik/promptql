pass

from typing import Any, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


RequiredString = Annotated[str, StringConstraints(min_length=1)]
CommitSha = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-fA-F]{40,64}$"),
]


class GitHubResponseModel(BaseModel):
    pass

    model_config = ConfigDict(extra="ignore", strict=True)


class GitHubUserResponse(GitHubResponseModel):
    login: RequiredString


class GitHubBranchResponse(GitHubResponseModel):
    ref: RequiredString
    sha: CommitSha


class GitHubPullRequestResponse(GitHubResponseModel):
    number: Annotated[int, Field(gt=0)]
    title: RequiredString
    body: str | None
    html_url: RequiredString
    state: Literal["open", "closed"]
    draft: bool
    merged: bool
    mergeable: bool | None
    user: GitHubUserResponse
    assignees: list[GitHubUserResponse]
    requested_reviewers: list[GitHubUserResponse]
    head: GitHubBranchResponse
    base: GitHubBranchResponse


class GitHubReviewResponse(GitHubResponseModel):
    user: GitHubUserResponse
    state: RequiredString


class GitHubRuleResponse(GitHubResponseModel):
    type: RequiredString
    parameters: dict[str, Any] | None = None


class GitHubRequiredStatusChecksResponse(GitHubResponseModel):
    contexts: list[RequiredString] = Field(default_factory=list)
    checks: list[dict[str, Any]] = Field(default_factory=list)


class GitHubRequiredReviewsResponse(GitHubResponseModel):
    required_approving_review_count: Annotated[int, Field(ge=0)]


class GitHubBranchProtectionResponse(GitHubResponseModel):
    required_status_checks: GitHubRequiredStatusChecksResponse | None
    required_pull_request_reviews: GitHubRequiredReviewsResponse | None


class GitHubCheckRunResponse(GitHubResponseModel):
    name: RequiredString
    status: RequiredString
    conclusion: str | None


class GitHubCheckRunsPageResponse(GitHubResponseModel):
    total_count: Annotated[int, Field(ge=0)]
    check_runs: list[GitHubCheckRunResponse]


class GitHubCommitStatusResponse(GitHubResponseModel):
    context: RequiredString
    state: RequiredString


class GitHubCommitStatusesPageResponse(GitHubResponseModel):
    total_count: Annotated[int, Field(ge=0)]
    statuses: list[GitHubCommitStatusResponse]
