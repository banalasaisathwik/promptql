from app.connectors.fixture_catalog import FixtureScenarioId
from app.connectors.models import (
    ConnectorRequest,
    ContractModel,
    GitHubPullRequest,
    JiraIssue,
    NonEmptyString,
)


class FixtureScenarioItem(ContractModel):
    id: FixtureScenarioId
    label: NonEmptyString
    request: ConnectorRequest


class FixtureScenarioCatalog(ContractModel):
    items: tuple[FixtureScenarioItem, ...]


class PullRequestInspection(ContractModel):
    request: ConnectorRequest
    github: GitHubPullRequest
    jira: JiraIssue
