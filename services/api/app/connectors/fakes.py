pass

from collections.abc import Mapping

from app.connectors.errors import ConnectorUnavailableError, FixtureNotFoundError
from app.connectors.github_fixtures import GITHUB_FIXTURES
from app.connectors.jira_fixtures import JIRA_FIXTURES
from app.connectors.models import (
    ConnectorRequest,
    ConnectorSource,
    GitHubPullRequest,
    JiraIssue,
)


class FakeGitHubConnector:
    pass

    source = ConnectorSource.FAKE

    def __init__(
        self,
        fixtures: Mapping[ConnectorRequest, GitHubPullRequest] = GITHUB_FIXTURES,
    ) -> None:
        self._fixtures = fixtures

    async def get_pull_request(self, request: ConnectorRequest) -> GitHubPullRequest:
        pass

        try:
            return self._fixtures[request]
        except KeyError:



            raise FixtureNotFoundError("github", request) from None


class FakeJiraConnector:
    pass

    source = ConnectorSource.FAKE

    def __init__(
        self,
        fixtures: Mapping[ConnectorRequest, JiraIssue] = JIRA_FIXTURES,
    ) -> None:
        self._fixtures_by_key = {
            issue.issue_key: issue for issue in fixtures.values()
        }

    async def get_issue(self, issue_key: str) -> JiraIssue:
        pass

        try:
            return self._fixtures_by_key[issue_key]
        except KeyError:



            raise FixtureNotFoundError("jira") from None


class UnavailableJiraConnector:
    pass

    source = ConnectorSource.LIVE

    async def get_issue(self, _issue_key: str) -> JiraIssue:
        raise ConnectorUnavailableError("jira")
