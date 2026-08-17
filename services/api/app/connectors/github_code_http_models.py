from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.connectors.models import CommitSha


RequiredString = Annotated[str, StringConstraints(min_length=1)]


class GitHubCodeResponseModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class GitHubCommitAuthorResponse(GitHubCodeResponseModel):
    date: RequiredString


class GitHubCommitDetailsResponse(GitHubCodeResponseModel):
    message: RequiredString
    author: GitHubCommitAuthorResponse | None


class GitHubCommitParentResponse(GitHubCodeResponseModel):
    sha: CommitSha


class GitHubCommitEvidenceResponse(GitHubCodeResponseModel):
    sha: CommitSha
    commit: GitHubCommitDetailsResponse
    parents: list[GitHubCommitParentResponse]


class GitHubCodeBranchResponse(GitHubCodeResponseModel):
    sha: CommitSha


class GitHubCodePullRequestResponse(GitHubCodeResponseModel):
    number: Annotated[int, Field(gt=0)]
    title: RequiredString
    state: Literal["open", "closed"]
    merged: bool
    merge_commit_sha: CommitSha | None
    head: GitHubCodeBranchResponse
    base: GitHubCodeBranchResponse


class GitHubChangedFileResponse(GitHubCodeResponseModel):
    filename: RequiredString
    previous_filename: RequiredString | None = None
    status: RequiredString
    additions: Annotated[int, Field(ge=0)]
    deletions: Annotated[int, Field(ge=0)]
    changes: Annotated[int, Field(ge=0)]
    patch: str | None = None
