pass

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.connector_router import router as connector_router
from app.api.v1.models import ApiError, ApiErrorCode
from app.connectors.errors import FixtureNotFoundError

                                                                            
                                             
app = FastAPI(title="PromptQL API")

                                                                               
                                                                         
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


@app.get("/health")
async def health() -> dict[str, str]:
    pass

    return {"status": "ok"}
