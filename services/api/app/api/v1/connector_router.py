pass

from fastapi import APIRouter

from app.api.v1.models import ApiError
from app.connectors.models import ConnectorRequest
from app.inspection.models import FixtureScenarioCatalog, PullRequestInspection
from app.inspection.service import (
    inspect_pull_request as run_pull_request_inspection,
)
from app.inspection.service import (
    list_fixture_scenarios,
)

router = APIRouter(prefix="/v1", tags=["pull-request-inspections"])


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
