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


def inspect_pull_request(request: ConnectorRequest) -> PullRequestInspection:
    pass

                                                                              
                                                                                
    github = FakeGitHubConnector().get_pull_request(request)
    jira = FakeJiraConnector().get_issue_for_pull_request(request)

    return PullRequestInspection(
        request=request,
        github=github,
        jira=jira,
    )
