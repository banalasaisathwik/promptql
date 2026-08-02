pass

from app.connectors.fixture_catalog import FixtureScenarioId
from app.connectors.models import (
    ConnectorRequest,
    ContractModel,
    GitHubPullRequest,
    JiraIssue,
    NonEmptyString,
)
from app.policy.models import MergeReadinessResult


class FixtureScenarioItem(ContractModel):
    pass

    id: FixtureScenarioId
    label: NonEmptyString
    request: ConnectorRequest


class FixtureScenarioCatalog(ContractModel):
    pass

    items: tuple[FixtureScenarioItem, ...]


class PullRequestInspection(ContractModel):
    pass

    request: ConnectorRequest
    github: GitHubPullRequest
    jira: JiraIssue


class PullRequestMergeReadiness(ContractModel):
    pass

    request: ConnectorRequest
    github: GitHubPullRequest | None
    jira: JiraIssue | None
    policy_result: MergeReadinessResult
