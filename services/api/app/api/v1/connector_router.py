from typing import Annotated

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.v1.models import (
    ApiError,
    ApiErrorCode,
    ExplanationApiError,
    LiveRunStartResponse,
    MergeReadinessResponse,
    RuntimePersistenceApiError,
)
from app.connectors.models import ConnectorRequest
from app.connectors.protocols import GitHubConnector, JiraConnector
from app.database import PostgresRunRepository
from app.explanations import (
    MergeReadinessExplanationError,
    MergeReadinessExplanationService,
)
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
from app.observability import (
    NoOpRuntimeTelemetry,
    ObservedRunRepository,
    RuntimeTelemetry,
)
from app.runtime import (
    ExplanationSource,
    MergeReadinessRun,
    RunPersistenceError,
    RunRepository,
    RunStatus,
    RunSources,
    LiveRunTaskRegistry,
)
from app.workflows import MergeReadinessWorkflowService

router = APIRouter(prefix="/v1", tags=["pull-request-inspections"])


def get_github_connector(request: Request) -> GitHubConnector:
    return request.app.state.github_connector


def get_jira_connector(request: Request) -> JiraConnector:
    return request.app.state.jira_connector


def get_runtime_telemetry(request: Request) -> RuntimeTelemetry:
    telemetry = getattr(request.app.state, "runtime_telemetry", None)
    if telemetry is not None:
        return telemetry
    return NoOpRuntimeTelemetry()


def get_run_repository(
    request: Request,
    telemetry: Annotated[RuntimeTelemetry, Depends(get_runtime_telemetry)],
) -> RunRepository:
    session_factory = getattr(request.app.state, "run_session_factory", None)
    if session_factory is None:
        raise RunPersistenceError("Runtime persistence is unavailable.")
    return ObservedRunRepository(
        inner=PostgresRunRepository(session_factory),
        telemetry=telemetry,
    )


def get_merge_readiness_explanation_service(
    request: Request,
) -> MergeReadinessExplanationService:
    return request.app.state.merge_readiness_explanation_service


def get_live_run_task_registry(request: Request) -> LiveRunTaskRegistry:
    return request.app.state.live_run_task_registry


def get_merge_readiness_workflow(
    github_connector: Annotated[GitHubConnector, Depends(get_github_connector)],
    jira_connector: Annotated[JiraConnector, Depends(get_jira_connector)],
    run_repository: Annotated[RunRepository, Depends(get_run_repository)],
    telemetry: Annotated[RuntimeTelemetry, Depends(get_runtime_telemetry)],
    explanation_service: Annotated[
        MergeReadinessExplanationService,
        Depends(get_merge_readiness_explanation_service),
    ],
) -> MergeReadinessWorkflowService:
    return MergeReadinessWorkflowService(
        github_connector,
        jira_connector,
        run_repository,
        telemetry=telemetry,
        explanation_provider=ExplanationSource(
            explanation_service.provider.value
        ),
    )


async def build_merge_readiness_response(
    run: MergeReadinessRun,
    explanation_service: MergeReadinessExplanationService,
) -> MergeReadinessResponse:
    explanation = None
    explanation_error = None
    sources = RunSources(
        github=run.sources.github if run.sources is not None else None,
        jira=run.sources.jira if run.sources is not None else None,
        explanation=ExplanationSource(explanation_service.provider.value),
    )
    if run.status is RunStatus.COMPLETED and run.result is not None:
        try:
            explanation = await explanation_service.explain(run.result)
        except MergeReadinessExplanationError as error:
            explanation_error = ExplanationApiError(
                code=error.code,
                message=error.message,
            )

    return MergeReadinessResponse.model_validate(
        {
            **run.model_dump(),
            "sources": sources,
            "explanation": explanation,
            "explanation_error": explanation_error,
        }
    )


@router.get(
    "/demo/pull-request-scenarios",
    response_model=FixtureScenarioCatalog,
)
async def list_pull_request_scenarios() -> FixtureScenarioCatalog:
    return list_fixture_scenarios()


@router.post(
    "/pull-request-inspections",
    response_model=PullRequestInspection,
    responses={404: {"model": ApiError}},
)
async def inspect_pull_request(request: ConnectorRequest) -> PullRequestInspection:
    return await run_pull_request_inspection(request)


@router.post(
    "/pull-request-merge-readiness",
    response_model=MergeReadinessResponse,
    responses={
        404: {"model": ApiError},
        500: {"model": MergeReadinessResponse},
        503: {"model": RuntimePersistenceApiError},
    },
)
async def analyze_pull_request(
    request: ConnectorRequest,
    workflow: Annotated[
        MergeReadinessWorkflowService,
        Depends(get_merge_readiness_workflow),
    ],
    telemetry: Annotated[RuntimeTelemetry, Depends(get_runtime_telemetry)],
    explanation_service: Annotated[
        MergeReadinessExplanationService,
        Depends(get_merge_readiness_explanation_service),
    ],
) -> MergeReadinessResponse | JSONResponse:
    terminal_run = await workflow.execute(request)
    telemetry.correlate_current_span(terminal_run)
    response = await build_merge_readiness_response(
        terminal_run,
        explanation_service,
    )
    if terminal_run.status is RunStatus.FAILED:
        return JSONResponse(
            status_code=500,
            content=response.model_dump(mode="json"),
        )
    return response


@router.post(
    "/pull-request-merge-readiness-runs",
    status_code=202,
    response_model=LiveRunStartResponse,
    responses={
        404: {"model": ApiError},
        503: {"model": RuntimePersistenceApiError},
    },
)
async def start_live_merge_readiness_run(
    request: ConnectorRequest,
    workflow: Annotated[
        MergeReadinessWorkflowService,
        Depends(get_merge_readiness_workflow),
    ],
    task_registry: Annotated[
        LiveRunTaskRegistry,
        Depends(get_live_run_task_registry),
    ],
) -> LiveRunStartResponse:
    pending_run = await workflow.create_persisted_run(request)
    task_registry.start(_continue_live_run(workflow, pending_run))
    return LiveRunStartResponse(run_id=pending_run.run_id, status=pending_run.status)


async def _continue_live_run(
    workflow: MergeReadinessWorkflowService,
    pending_run: MergeReadinessRun,
) -> None:
    try:
        await workflow.continue_persisted_run(pending_run)
    except Exception:
        return


@router.get(
    "/runs/{run_id}",
    response_model=MergeReadinessResponse,
    responses={
        404: {"model": ApiError},
        500: {"model": ApiError},
        503: {"model": RuntimePersistenceApiError},
    },
)
async def get_runtime_run(
    run_id: UUID,
    run_repository: Annotated[RunRepository, Depends(get_run_repository)],
    explanation_service: Annotated[
        MergeReadinessExplanationService,
        Depends(get_merge_readiness_explanation_service),
    ],
) -> MergeReadinessResponse | JSONResponse:
    stored_run = run_repository.get(run_id)
    if stored_run is None:
        error = ApiError(
            code=ApiErrorCode.RUN_NOT_FOUND,
            message="No runtime run exists for this ID.",
        )
        return JSONResponse(status_code=404, content=error.model_dump(mode="json"))
    return await build_merge_readiness_response(stored_run, explanation_service)
