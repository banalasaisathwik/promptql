from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.connector_router import router as connector_router
from app.api.v1.models import (
    ApiError,
    ApiErrorCode,
    RuntimePersistenceApiError,
)
from app.config import (
    DatabaseSettings,
    GitHubConnectorMode,
    GitHubSettings,
    JiraConnectorMode,
    JiraSettings,
    LLMProvider,
    LLMSettings,
    LLMTask,
)
from app.connectors.errors import FixtureNotFoundError
from app.connectors.factory import (
    create_github_code_evidence_source,
    create_github_connector,
    create_github_http_client,
    create_jira_connector,
    create_jira_http_client,
)
from app.connectors.github_http import HttpGitHubConnector
from app.connectors.jira_http import HttpJiraConnector
from app.database import (
    create_database_engine,
    create_session_factory,
    verify_database_ready,
)
from app.explanations import (
    GeminiLLMClient,
    GroqLLMClient,
    LLMClient,
    MergeReadinessExplanationService,
    OpenAILLMClient,
    OpenRouterLLMClient,
    create_llm_client,
)
from app.observability import Observability, create_observability
from app.runtime import (
    LiveRunTaskRegistry,
    RunPersistenceError,
    RunRecordInvalidError,
    RunStateConflictError,
)
from app.workflows import InvestigationWorkflowService


async def fixture_not_found_handler(
    _request: Request,
    _error: FixtureNotFoundError,
) -> JSONResponse:
    error = ApiError(
        code=ApiErrorCode.FIXTURE_NOT_FOUND,
        message="No connector fixture exists for this pull request.",
    )
    return JSONResponse(status_code=404, content=error.model_dump(mode="json"))


async def run_persistence_error_handler(
    _request: Request,
    error: RunPersistenceError,
) -> JSONResponse:
    response = RuntimePersistenceApiError(
        code=ApiErrorCode.RUNTIME_PERSISTENCE_UNAVAILABLE,
        message="Runtime persistence is unavailable.",
        run_id=error.run_id,
    )
    return JSONResponse(status_code=503, content=response.model_dump(mode="json"))


async def run_state_conflict_handler(
    _request: Request,
    error: RunStateConflictError,
) -> JSONResponse:
    response = RuntimePersistenceApiError(
        code=ApiErrorCode.RUNTIME_STATE_CONFLICT,
        message="The stored runtime state changed and could not be updated.",
        run_id=error.run_id,
    )
    return JSONResponse(status_code=409, content=response.model_dump(mode="json"))


async def run_record_invalid_handler(
    _request: Request,
    _error: RunRecordInvalidError,
) -> JSONResponse:
    response = ApiError(
        code=ApiErrorCode.RUNTIME_RECORD_INVALID,
        message="The stored runtime record could not be reconstructed.",
    )
    return JSONResponse(status_code=500, content=response.model_dump(mode="json"))


async def health() -> dict[str, str]:
    return {"status": "ok"}


def create_app(
    observability: Observability | None = None,
    github_settings: GitHubSettings | None = None,
    jira_settings: JiraSettings | None = None,
    llm_settings: LLMSettings | None = None,
    llm_client: LLMClient | None = None,
) -> FastAPI:
    if observability is not None:
        app_observability = observability
    else:
        app_observability = create_observability()

    if github_settings is not None:
        resolved_github_settings = github_settings
    else:
        resolved_github_settings = GitHubSettings.from_environment()

    if jira_settings is not None:
        resolved_jira_settings = jira_settings
    else:
        resolved_jira_settings = JiraSettings.from_environment()

    github_http_client = None
    if resolved_github_settings.mode is GitHubConnectorMode.GITHUB:
        github_http_client = create_github_http_client(resolved_github_settings)

    github_connector = create_github_connector(
        resolved_github_settings,
        app_observability.runtime_telemetry,
        github_http_client,
    )
    github_code_source = create_github_code_evidence_source(
        resolved_github_settings,
        app_observability.runtime_telemetry,
        github_http_client,
    )

    jira_http_client = None
    if resolved_jira_settings.mode is JiraConnectorMode.JIRA:
        jira_http_client = create_jira_http_client(resolved_jira_settings)

    jira_connector = create_jira_connector(
        resolved_jira_settings,
        app_observability.runtime_telemetry,
        jira_http_client,
    )

    if llm_client is not None:
        selected_llm_client = llm_client
        investigation_planner_client = llm_client
        investigation_hypothesis_client = llm_client
    else:
        resolved_llm_settings = llm_settings or LLMSettings.from_environment()
        if resolved_llm_settings.provider is LLMProvider.FAKE:
            # Fake mode intentionally has neither a model nor a ModelPolicy.
            # Branch before `model_for()` so Python never evaluates that
            # non-fake-only lookup while constructing the local/test client.
            selected_llm_client = create_llm_client(resolved_llm_settings)
            investigation_planner_client = selected_llm_client
            investigation_hypothesis_client = selected_llm_client
        else:
            # V1 explanations have no separate task policy yet. When this service
            # starts with investigation-only task models, use planning as the
            # explicit compatibility choice instead of requiring a hidden global ID.
            selected_llm_client = create_llm_client(
                resolved_llm_settings,
                resolved_llm_settings.model
                or resolved_llm_settings.model_for(LLMTask.PLANNING),
            )
            # The policy is deterministic: the same task and settings always
            # construct a client for the same requested model.
            investigation_planner_client = create_llm_client(
                resolved_llm_settings,
                resolved_llm_settings.model_for(LLMTask.PLANNING),
            )
            investigation_hypothesis_client = create_llm_client(
                resolved_llm_settings,
                resolved_llm_settings.model_for(LLMTask.HYPOTHESIS_GENERATION),
            )
    explanation_service = MergeReadinessExplanationService(
        selected_llm_client,
        telemetry=app_observability.runtime_telemetry,
    )
    live_run_task_registry = LiveRunTaskRegistry()


    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = None
        try:
            if app_observability.event_logger is not None:
                app_observability.event_logger.emit(
                    "runtime.connector_sources.selected",
                    github_source=github_connector.source,
                    jira_source=jira_connector.source,
                )
            settings = DatabaseSettings.from_environment()
            engine = create_database_engine(settings)
            verify_database_ready(engine)
            application.state.run_session_factory = create_session_factory(engine)
            yield
        finally:
            await live_run_task_registry.shutdown()
            application.state.run_session_factory = None
            application.state.live_run_task_registry = None
            if engine is not None:
                engine.dispose()
            if isinstance(github_connector, HttpGitHubConnector):
                await github_connector.aclose()
            if isinstance(jira_connector, HttpJiraConnector):
                await jira_connector.aclose()
            for client in {
                id(selected_llm_client): selected_llm_client,
                id(investigation_planner_client): investigation_planner_client,
                id(investigation_hypothesis_client): investigation_hypothesis_client,
            }.values():
                if isinstance(
                    client,
                    (GeminiLLMClient, GroqLLMClient, OpenAILLMClient, OpenRouterLLMClient),
                ):
                    await client.aclose()
            app_observability.shutdown()


    application = FastAPI(title="PromptQL API", lifespan=lifespan)
    application.state.runtime_telemetry = app_observability.runtime_telemetry
    application.state.github_connector = github_connector
    application.state.jira_connector = jira_connector
    application.state.merge_readiness_explanation_service = explanation_service
    application.state.investigation_llm_client = selected_llm_client
    application.state.investigation_planner_client = investigation_planner_client
    application.state.investigation_hypothesis_client = investigation_hypothesis_client
    application.state.github_code_source = github_code_source
    application.state.live_run_task_registry = live_run_task_registry
    application.include_router(connector_router)
    application.add_exception_handler(
        FixtureNotFoundError,
        fixture_not_found_handler,
    )
    application.add_exception_handler(
        RunPersistenceError,
        run_persistence_error_handler,
    )
    application.add_exception_handler(
        RunStateConflictError,
        run_state_conflict_handler,
    )
    application.add_exception_handler(
        RunRecordInvalidError,
        run_record_invalid_handler,
    )
    application.add_api_route("/health", health, methods=["GET"])
    app_observability.instrument_app(application)
    return application


app = create_app()
