pass

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
from app.config import DatabaseSettings, GitHubConnectorMode, GitHubSettings
from app.connectors.factory import (
    create_github_connector,
    create_github_http_client,
)
from app.connectors.fakes import FakeJiraConnector, UnavailableJiraConnector
from app.connectors.errors import FixtureNotFoundError
from app.connectors.github_http import HttpGitHubConnector
from app.database import (
    create_database_engine,
    create_session_factory,
    verify_database_ready,
)
from app.observability import Observability, create_observability
from app.runtime import (
    RunPersistenceError,
    RunRecordInvalidError,
    RunStateConflictError,
)


async def fixture_not_found_handler(
    _request: Request,
    _error: FixtureNotFoundError,
) -> JSONResponse:
    pass

    error = ApiError(
        code=ApiErrorCode.FIXTURE_NOT_FOUND,
        message="No connector fixture exists for this pull request.",
    )
    return JSONResponse(status_code=404, content=error.model_dump(mode="json"))


async def run_persistence_error_handler(
    _request: Request,
    error: RunPersistenceError,
) -> JSONResponse:
    pass

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
    pass

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
    pass

    response = ApiError(
        code=ApiErrorCode.RUNTIME_RECORD_INVALID,
        message="The stored runtime record could not be reconstructed.",
    )
    return JSONResponse(status_code=500, content=response.model_dump(mode="json"))


async def health() -> dict[str, str]:
    pass

    return {"status": "ok"}


def create_app(
    observability: Observability | None = None,
    github_settings: GitHubSettings | None = None,
) -> FastAPI:
    pass

    app_observability = observability or create_observability()
    resolved_github_settings = github_settings or GitHubSettings.from_environment()
    github_http_client = (
        create_github_http_client(resolved_github_settings)
        if resolved_github_settings.mode is GitHubConnectorMode.GITHUB
        else None
    )
    github_connector = create_github_connector(
        resolved_github_settings,
        app_observability.runtime_telemetry,
        github_http_client,
    )
    jira_connector = (
        UnavailableJiraConnector()
        if resolved_github_settings.mode is GitHubConnectorMode.GITHUB
        else FakeJiraConnector()
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        pass

        engine = None
        try:
            settings = DatabaseSettings.from_environment()
            engine = create_database_engine(settings)
            verify_database_ready(engine)
            application.state.run_session_factory = create_session_factory(engine)
            yield
        finally:
            application.state.run_session_factory = None
            if engine is not None:
                engine.dispose()
            if isinstance(github_connector, HttpGitHubConnector):
                await github_connector.aclose()
            app_observability.shutdown()

    application = FastAPI(title="PromptQL API", lifespan=lifespan)
    application.state.runtime_telemetry = app_observability.runtime_telemetry
    application.state.github_connector = github_connector
    application.state.jira_connector = jira_connector
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
