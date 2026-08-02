pass

from typing import Protocol

from app.connectors.errors import ConnectorUnavailableError
from app.connectors.fakes import FakeGitHubConnector, FakeJiraConnector
from app.connectors.fixture_catalog import FIXTURE_SCENARIOS
from app.connectors.models import ConnectorRequest, GitHubPullRequest, JiraIssue
from app.inspection.models import (
    FixtureScenarioCatalog,
    FixtureScenarioItem,
    PullRequestInspection,
    PullRequestMergeReadiness,
)
from app.policy import evaluate_merge_readiness


class GitHubConnector(Protocol):
    pass

    def get_pull_request(self, request: ConnectorRequest) -> GitHubPullRequest: ...


class JiraConnector(Protocol):
    pass

    def get_issue_for_pull_request(self, request: ConnectorRequest) -> JiraIssue: ...


def list_fixture_scenarios() -> FixtureScenarioCatalog:
    pass



    items = tuple(
        FixtureScenarioItem(
            id=scenario.id,
            label=scenario.label,
            request=scenario.request,
        )
        for scenario in FIXTURE_SCENARIOS
    )
    return FixtureScenarioCatalog(items=items)


def inspect_pull_request(request: ConnectorRequest) -> PullRequestInspection:
    pass



    github = FakeGitHubConnector().get_pull_request(request)
    jira = FakeJiraConnector().get_issue_for_pull_request(request)

    return PullRequestInspection(
        request=request,
        github=github,
        jira=jira,
    )


def analyze_pull_request_merge_readiness(
    request: ConnectorRequest,
    github_connector: GitHubConnector,
    jira_connector: JiraConnector,
) -> PullRequestMergeReadiness:
    pass

    try:
        github = github_connector.get_pull_request(request)
    except ConnectorUnavailableError:
        github = None

    try:
        jira = jira_connector.get_issue_for_pull_request(request)
    except ConnectorUnavailableError:
        jira = None

    policy_result = evaluate_merge_readiness(github, jira)

    return PullRequestMergeReadiness(
        request=request,
        github=github,
        jira=jira,
        policy_result=policy_result,
    )
