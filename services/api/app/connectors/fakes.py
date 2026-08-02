pass

from collections.abc import Mapping

from app.connectors.errors import FixtureNotFoundError
from app.connectors.github_fixtures import GITHUB_FIXTURES
from app.connectors.jira_fixtures import JIRA_FIXTURES
from app.connectors.models import ConnectorRequest, GitHubPullRequest, JiraIssue


class FakeGitHubConnector:
    pass

    def __init__(
        self,
        fixtures: Mapping[ConnectorRequest, GitHubPullRequest] = GITHUB_FIXTURES,
    ) -> None:
        self._fixtures = fixtures

    def get_pull_request(self, request: ConnectorRequest) -> GitHubPullRequest:
        pass

        try:
            return self._fixtures[request]
        except KeyError:
                                                                              
                                                                            
                                                                               
            raise FixtureNotFoundError("github", request) from None


class FakeJiraConnector:
    pass

    def __init__(
        self,
        fixtures: Mapping[ConnectorRequest, JiraIssue] = JIRA_FIXTURES,
    ) -> None:
        self._fixtures = fixtures

    def get_issue_for_pull_request(self, request: ConnectorRequest) -> JiraIssue:
        pass

        try:
            return self._fixtures[request]
        except KeyError:
                                                                            
                                                                               
            raise FixtureNotFoundError("jira", request) from None
