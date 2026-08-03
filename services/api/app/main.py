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
from app.config import DatabaseSettings
from app.connectors.errors import FixtureNotFoundError
from app.database import (
    create_database_engine,
    create_session_factory,
    verify_database_ready,
)
from app.runtime import (
    RunPersistenceError,
    RunRecordInvalidError,
    RunStateConflictError,
)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    pass

    settings = DatabaseSettings.from_environment()
    engine = create_database_engine(settings)
    try:
        verify_database_ready(engine)
        application.state.run_session_factory = create_session_factory(engine)
        yield
    finally:
        application.state.run_session_factory = None
        engine.dispose()



app = FastAPI(title="PromptQL API", lifespan=lifespan)



app.include_router(connector_router)


@app.exception_handler(FixtureNotFoundError)
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


@app.exception_handler(RunPersistenceError)
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


@app.exception_handler(RunStateConflictError)
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


@app.exception_handler(RunRecordInvalidError)
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


@app.get("/health")
async def health() -> dict[str, str]:
    pass

    return {"status": "ok"}
