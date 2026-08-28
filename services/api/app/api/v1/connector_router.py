import asyncio
import os
from collections.abc import AsyncIterator
from typing import Annotated

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.v1.models import (
    ApiError,
    ApiErrorCode,
    ExplanationApiError,
    FollowUpInvestigationRequest,
    GroundingExtractionApiError,
    GroundingExtractionApiErrorCode,
    GroundingExtractionResponse,
    GroundingExtractionStatus,
    InvestigationFollowUpStartResponse,
    LiveRunStartResponse,
    MergeReadinessResponse,
    MissingGroundingField,
    InvestigationResponse,
    RuntimePersistenceApiError,
)
from app.api.v1.auth_router import get_current_user_optional
from app.api.v1.credentials_router import get_credential_repository
from app.api.v1.request_lifecycle import request_scoped_http_client
from app.auth import CredentialProvider, User
from app.config import GitHubSettings, JiraSettings, SentrySettings
from app.connectors.factory import (
    create_github_code_evidence_source,
    create_github_connector,
    create_github_http_client,
    create_incident_source,
    create_jira_connector,
    create_jira_http_client,
    create_sentry_http_client,
)
from app.connectors.models import ConnectorRequest
from app.investigations.grounding_extraction import (
    GroundingExtractionError,
    GroundingExtractionFailureCode,
    GroundingExtractionInput,
    TypedGroundingExtractor,
)
from app.investigations.models import InvestigationRequest, has_required_grounding_reference
from app.connectors.protocols import (
    GitHubCodeEvidenceSource,
    GitHubConnector,
    IncidentSource,
    JiraConnector,
)
from app.database import PostgresFactRecurrenceRepository, PostgresRunRepository
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
    FactRecurrenceRepository,
    MergeReadinessRun,
    RunPersistenceError,
    RunRepository,
    RunStateConflictError,
    RunStatus,
    RunSources,
    LiveRunTaskRegistry,
)
from app.runtime.investigation_models import InvestigationRun
from app.workflows import InvestigationWorkflowService, MergeReadinessWorkflowService

router = APIRouter(prefix="/v1", tags=["pull-request-inspections"])


async def get_github_connector(
    request: Request,
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> AsyncIterator[GitHubConnector]:
    if current_user is None:
        yield request.app.state.github_connector
        return

    credential_repository = get_credential_repository(request)
    token = credential_repository.get_decrypted_credential(
        current_user.id, CredentialProvider.GITHUB
    )
    if token is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Connect your GitHub account before starting an investigation that needs it."
            ),
        )

    settings = GitHubSettings.from_stored_credential(token)
    async for http_client in request_scoped_http_client(
        lambda: create_github_http_client(settings)
    ):
        yield create_github_connector(
            settings, get_runtime_telemetry(request), http_client
        )


async def get_github_code_evidence_source(
    request: Request,
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> AsyncIterator[GitHubCodeEvidenceSource]:
    if current_user is None:
        yield request.app.state.github_code_source
        return

    credential_repository = get_credential_repository(request)
    token = credential_repository.get_decrypted_credential(
        current_user.id, CredentialProvider.GITHUB
    )
    if token is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Connect your GitHub account before starting an investigation that needs it."
            ),
        )

    settings = GitHubSettings.from_stored_credential(token)
    async for http_client in request_scoped_http_client(
        lambda: create_github_http_client(settings)
    ):
        yield create_github_code_evidence_source(
            settings, get_runtime_telemetry(request), http_client
        )


async def get_jira_connector(
    request: Request,
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> AsyncIterator[JiraConnector]:
    if current_user is None:
        yield request.app.state.jira_connector
        return

    credential_repository = get_credential_repository(request)
    token = credential_repository.get_decrypted_credential(
        current_user.id, CredentialProvider.JIRA
    )
    if token is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Connect your Jira account before starting an investigation that needs it."
            ),
        )

    settings = JiraSettings.from_stored_credential(
        token,
        base_url=os.environ.get("JIRA_BASE_URL", ""),
        email=os.environ.get("JIRA_EMAIL", ""),
    )
    async for http_client in request_scoped_http_client(
        lambda: create_jira_http_client(settings)
    ):
        yield create_jira_connector(
            settings, get_runtime_telemetry(request), http_client
        )


async def get_incident_source(
    request: Request,
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> AsyncIterator[IncidentSource]:
    if current_user is None:
        yield request.app.state.incident_source
        return

    credential_repository = get_credential_repository(request)
    token = credential_repository.get_decrypted_credential(
        current_user.id, CredentialProvider.SENTRY
    )
    if token is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Connect your Sentry account before starting an investigation that needs it."
            ),
        )

    settings = SentrySettings.from_stored_credential(
        token,
        organization_slug=os.environ.get("SENTRY_ORGANIZATION_SLUG", ""),
    )
    async for http_client in request_scoped_http_client(
        lambda: create_sentry_http_client(settings)
    ):
        yield create_incident_source(
            settings, get_runtime_telemetry(request), http_client
        )


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


def get_fact_recurrence_repository(request: Request) -> FactRecurrenceRepository:
    session_factory = getattr(request.app.state, "run_session_factory", None)
    if session_factory is None:
        raise RunPersistenceError("Runtime persistence is unavailable.")
    return PostgresFactRecurrenceRepository(session_factory)


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


def get_investigation_workflow(
    request: Request,
    run_repository: Annotated[RunRepository, Depends(get_run_repository)],
    fact_recurrence_repository: Annotated[
        FactRecurrenceRepository, Depends(get_fact_recurrence_repository)
    ],
    github_code_source: Annotated[
        GitHubCodeEvidenceSource, Depends(get_github_code_evidence_source)
    ],
    incident_source: Annotated[IncidentSource, Depends(get_incident_source)],
    jira_connector: Annotated[JiraConnector, Depends(get_jira_connector)],
) -> InvestigationWorkflowService:
    return InvestigationWorkflowService(
        run_repository,
        request.app.state.investigation_hypothesis_client,
        planner_client=request.app.state.investigation_planner_client,
        code_diagnosis_client=request.app.state.investigation_code_diagnosis_client,
        github_code_source=github_code_source,
        incident_source=incident_source,
        jira_connector=jira_connector,
        telemetry=request.app.state.runtime_telemetry,
        fact_recurrence_repository=fact_recurrence_repository,
    )


def get_grounding_extractor(request: Request) -> TypedGroundingExtractor:
    return TypedGroundingExtractor(request.app.state.investigation_planner_client)


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


@router.post(
    "/investigations",
    status_code=202,
    response_model=LiveRunStartResponse,
    responses={503: {"model": RuntimePersistenceApiError}},
)
async def start_investigation(
    request: InvestigationRequest,
    workflow: Annotated[
        InvestigationWorkflowService,
        Depends(get_investigation_workflow),
    ],
    task_registry: Annotated[
        LiveRunTaskRegistry,
        Depends(get_live_run_task_registry),
    ],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> LiveRunStartResponse:
    pending_run = await workflow.create_persisted_run(
        request,
        user_id=current_user.id if current_user is not None else None,
    )
    task_registry.start(_continue_investigation(workflow, pending_run))
    return LiveRunStartResponse(run_id=pending_run.run_id, status=pending_run.status)


_GROUNDING_EXTRACTION_FAILURE_CODES = {
    GroundingExtractionFailureCode.PROVIDER_FAILURE: GroundingExtractionApiErrorCode.PROVIDER_FAILURE,
    GroundingExtractionFailureCode.INVALID_RESPONSE: GroundingExtractionApiErrorCode.INVALID_RESPONSE,
    GroundingExtractionFailureCode.EXTRACTION_SCHEMA_INVALID: (
        GroundingExtractionApiErrorCode.EXTRACTION_SCHEMA_INVALID
    ),
}


@router.post(
    "/investigations/extract-grounding",
    response_model=GroundingExtractionResponse,
    responses={502: {"model": GroundingExtractionApiError}},
)
async def extract_grounding(
    request: GroundingExtractionInput,
    extractor: Annotated[TypedGroundingExtractor, Depends(get_grounding_extractor)],
) -> GroundingExtractionResponse | JSONResponse:
    try:
        extracted = await extractor.extract(request)
    except GroundingExtractionError as error:
        return JSONResponse(
            status_code=502,
            content=GroundingExtractionApiError(
                code=_GROUNDING_EXTRACTION_FAILURE_CODES[error.code],
                message=str(error),
            ).model_dump(mode="json"),
        )

    if has_required_grounding_reference(
        extracted.incident_reference,
        extracted.pull_request_number,
        extracted.deployment_reference,
    ):
        return GroundingExtractionResponse(
            status=GroundingExtractionStatus.COMPLETE,
            extracted=extracted,
        )

    missing = tuple(
        field
        for field, value in (
            (MissingGroundingField.INCIDENT_REFERENCE, extracted.incident_reference),
            (MissingGroundingField.DEPLOYMENT_REFERENCE, extracted.deployment_reference),
            (MissingGroundingField.PULL_REQUEST_NUMBER, extracted.pull_request_number),
        )
        if value is None
    )
    return GroundingExtractionResponse(
        status=GroundingExtractionStatus.NEEDS_CLARIFICATION,
        extracted=extracted,
        missing=missing,
        question=(
            "Which incident, deployment, or pull request is this about? "
            "For example, an incident ID, a deployment reference, or a PR number."
        ),
    )


async def _continue_live_run(
    workflow: MergeReadinessWorkflowService,
    pending_run: MergeReadinessRun,
) -> None:
    try:
        await workflow.continue_persisted_run(pending_run)
    except Exception:
        return


async def _continue_investigation(
    workflow: InvestigationWorkflowService,
    pending_run,
) -> None:
    try:
        await workflow.continue_persisted_run(pending_run)
    except asyncio.CancelledError:
        raise
    except Exception:
        return


async def _continue_investigation_follow_up(
    workflow: InvestigationWorkflowService,
    reopened_run: InvestigationRun,
    follow_up_question: str,
) -> None:
    try:
        await workflow.continue_persisted_run(
            reopened_run, follow_up_question=follow_up_question
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        return


@router.post(
    "/investigations/{run_id}/follow-up",
    status_code=202,
    response_model=InvestigationFollowUpStartResponse,
    responses={
        404: {"model": ApiError},
        409: {"model": RuntimePersistenceApiError},
        503: {"model": RuntimePersistenceApiError},
    },
)
async def start_investigation_follow_up(
    run_id: UUID,
    request: FollowUpInvestigationRequest,
    workflow: Annotated[
        InvestigationWorkflowService,
        Depends(get_investigation_workflow),
    ],
    run_repository: Annotated[RunRepository, Depends(get_run_repository)],
    task_registry: Annotated[
        LiveRunTaskRegistry,
        Depends(get_live_run_task_registry),
    ],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> InvestigationFollowUpStartResponse | JSONResponse:
    stored_run = (
        run_repository.get(run_id, current_user.id)
        if current_user is not None
        else run_repository.get(run_id)
    )
    if stored_run is None or not isinstance(stored_run, InvestigationRun):
        error = ApiError(
            code=ApiErrorCode.RUN_NOT_FOUND,
            message="No investigation exists for this ID.",
        )
        return JSONResponse(status_code=404, content=error.model_dump(mode="json"))
    try:
        reopened_run = await workflow.reopen_for_follow_up(stored_run)
    except RunStateConflictError as error:
        response = RuntimePersistenceApiError(
            code=ApiErrorCode.RUNTIME_STATE_CONFLICT,
            message=str(error),
            run_id=run_id,
        )
        return JSONResponse(status_code=409, content=response.model_dump(mode="json"))
    task_registry.start(
        _continue_investigation_follow_up(workflow, reopened_run, request.question)
    )
    return InvestigationFollowUpStartResponse(
        run_id=reopened_run.run_id, status=reopened_run.status
    )


@router.get(
    "/runs/{run_id}",
    response_model=MergeReadinessResponse | InvestigationResponse,
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
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> MergeReadinessResponse | InvestigationResponse | JSONResponse:
    stored_run = (
        run_repository.get(run_id, current_user.id)
        if current_user is not None
        else run_repository.get(run_id)
    )
    if stored_run is None:
        error = ApiError(
            code=ApiErrorCode.RUN_NOT_FOUND,
            message="No runtime run exists for this ID.",
        )
        return JSONResponse(status_code=404, content=error.model_dump(mode="json"))
    if stored_run.workflow_name == "investigation":
        return InvestigationResponse.model_validate(stored_run.model_dump())
    return await build_merge_readiness_response(stored_run, explanation_service)
