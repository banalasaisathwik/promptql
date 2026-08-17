from typing import Protocol

from app.connectors.models import (
    ConnectorRequest,
    ConnectorSource,
    GitHubCommitEvidenceRequest,
    GitHubPullRequest,
    GitHubPullRequestEvidenceRequest,
    JiraIssue,
)
from app.investigations import Evidence


class GitHubConnector(Protocol):
    source: ConnectorSource


    async def get_pull_request(
        self,
        request: ConnectorRequest,
    ) -> GitHubPullRequest: ...


class GitHubCodeEvidenceSource(Protocol):
    source: ConnectorSource

    async def get_commit_evidence(
        self,
        request: GitHubCommitEvidenceRequest,
    ) -> Evidence: ...

    async def get_pull_request_evidence(
        self,
        request: GitHubPullRequestEvidenceRequest,
    ) -> Evidence: ...

    async def get_changed_file_evidence(
        self,
        request: GitHubPullRequestEvidenceRequest,
    ) -> tuple[Evidence, ...]: ...


class JiraConnector(Protocol):
    source: ConnectorSource


    async def get_issue(self, issue_key: str) -> JiraIssue: ...
