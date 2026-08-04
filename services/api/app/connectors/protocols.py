pass

from typing import Protocol

from app.connectors.models import (
    ConnectorRequest,
    ConnectorSource,
    GitHubPullRequest,
    JiraIssue,
)


class GitHubConnector(Protocol):
    pass

    source: ConnectorSource

    async def get_pull_request(
        self,
        request: ConnectorRequest,
    ) -> GitHubPullRequest: ...


class JiraConnector(Protocol):
    pass

    def get_issue_for_pull_request(self, request: ConnectorRequest) -> JiraIssue: ...
