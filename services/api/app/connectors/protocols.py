from typing import Protocol

from app.connectors.models import (
    ConnectorRequest,
    ConnectorSource,
    GitHubPullRequest,
    JiraIssue,
)


class GitHubConnector(Protocol):
    source: ConnectorSource


    async def get_pull_request(
        self,
        request: ConnectorRequest,
    ) -> GitHubPullRequest: ...


class JiraConnector(Protocol):
    source: ConnectorSource


    async def get_issue(self, issue_key: str) -> JiraIssue: ...
