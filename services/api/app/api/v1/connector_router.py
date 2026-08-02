pass

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.v1.models import ApiError
from app.connectors.models import ConnectorRequest
from app.connectors.fakes import FakeGitHubConnector, FakeJiraConnector
from app.inspection.models import (
    FixtureScenarioCatalog,
    PullRequestInspection,
    PullRequestMergeReadiness,
)
from app.inspection.service import (
    analyze_pull_request_merge_readiness,
    inspect_pull_request as run_pull_request_inspection,
)
from app.inspection.service import (
    list_fixture_scenarios,
)

router = APIRouter(prefix="/v1", tags=["pull-request-inspections"])


def get_github_connector() -> FakeGitHubConnector:
    pass

    return FakeGitHubConnector()


def get_jira_connector() -> FakeJiraConnector:
    pass

    return FakeJiraConnector()


@router.get(
    "/demo/pull-request-scenarios",
    response_model=FixtureScenarioCatalog,
)
async def list_pull_request_scenarios() -> FixtureScenarioCatalog:
    pass

    return list_fixture_scenarios()


@router.post(
    "/pull-request-inspections",
    response_model=PullRequestInspection,
    responses={404: {"model": ApiError}},
)
async def inspect_pull_request(request: ConnectorRequest) -> PullRequestInspection:
    pass

    return run_pull_request_inspection(request)


@router.post(
    "/pull-request-merge-readiness",
    response_model=PullRequestMergeReadiness,
    responses={404: {"model": ApiError}},
)
async def analyze_pull_request(
    request: ConnectorRequest,
    github_connector: Annotated[FakeGitHubConnector, Depends(get_github_connector)],
    jira_connector: Annotated[FakeJiraConnector, Depends(get_jira_connector)],
) -> PullRequestMergeReadiness:
    pass

    return analyze_pull_request_merge_readiness(
        request,
        github_connector,
        jira_connector,
    )
