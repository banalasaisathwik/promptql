pass

from app.connectors.fakes import FakeGitHubConnector, FakeJiraConnector
from app.connectors.fixture_catalog import FIXTURE_SCENARIOS
from app.connectors.models import ConnectorRequest
from app.inspection.models import (
    FixtureScenarioCatalog,
    FixtureScenarioItem,
    PullRequestInspection,
)


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


async def inspect_pull_request(request: ConnectorRequest) -> PullRequestInspection:
    pass



    github = await FakeGitHubConnector().get_pull_request(request)
    if github.linked_jira_key is None:
        raise RuntimeError("fixture GitHub facts must contain a Jira key")
    jira = await FakeJiraConnector().get_issue(github.linked_jira_key)

    return PullRequestInspection(
        request=request,
        github=github,
        jira=jira,
    )
