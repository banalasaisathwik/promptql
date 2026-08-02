pass

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.v1.models import ApiError
from app.connectors.models import ConnectorRequest
from app.connectors.fakes import FakeGitHubConnector, FakeJiraConnector
from app.inspection.models import (
    FixtureScenarioCatalog,
    PullRequestInspection,
)
from app.inspection.service import (
    inspect_pull_request as run_pull_request_inspection,
)
from app.inspection.service import (
    list_fixture_scenarios,
)
from app.runtime import InMemoryRunRepository, MergeReadinessRun, RunStatus
from app.workflows import MergeReadinessWorkflowService

router = APIRouter(prefix="/v1", tags=["pull-request-inspections"])


def get_github_connector() -> FakeGitHubConnector:
    pass

    return FakeGitHubConnector()


def get_jira_connector() -> FakeJiraConnector:
    pass

    return FakeJiraConnector()


def get_run_repository() -> InMemoryRunRepository:
    pass

    return InMemoryRunRepository()


def get_merge_readiness_workflow(
    github_connector: Annotated[FakeGitHubConnector, Depends(get_github_connector)],
    jira_connector: Annotated[FakeJiraConnector, Depends(get_jira_connector)],
    run_repository: Annotated[InMemoryRunRepository, Depends(get_run_repository)],
) -> MergeReadinessWorkflowService:
    pass

    return MergeReadinessWorkflowService(
        github_connector,
        jira_connector,
        run_repository,
    )


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
    response_model=MergeReadinessRun,
    responses={
        404: {"model": ApiError},
        500: {"model": MergeReadinessRun},
    },
)
async def analyze_pull_request(
    request: ConnectorRequest,
    workflow: Annotated[
        MergeReadinessWorkflowService,
        Depends(get_merge_readiness_workflow),
    ],
) -> MergeReadinessRun | JSONResponse:
    pass

    run = workflow.execute(request)
    if run.status is RunStatus.FAILED:
        return JSONResponse(
            status_code=500,
            content=run.model_dump(mode="json"),
        )
    return run
