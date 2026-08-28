import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.v1.auth_router import get_current_user_optional
from app.api.v1.connector_router import get_run_repository
from app.api.v1.models import ApiError, ApiErrorCode
from app.auth import User
from app.observability.live_event_broker import LiveEventBroker
from app.runtime import RunRepository


router = APIRouter(prefix="/v1", tags=["live-events"])

KEEP_ALIVE_INTERVAL_SECONDS = 15


def get_live_event_broker(request: Request) -> LiveEventBroker:
    return request.app.state.live_event_broker


async def _stream_events(
    broker: LiveEventBroker,
    run_id: UUID,
    *,
    poll_interval_seconds: float = KEEP_ALIVE_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    subscriber_key = str(run_id)
    queue = broker.subscribe(subscriber_key)
    try:
        while True:
            try:
                event = await asyncio.wait_for(
                    queue.get(), timeout=poll_interval_seconds
                )
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield f"data: {json.dumps(event, separators=(',', ':'), sort_keys=True)}\n\n"
    finally:
        broker.unsubscribe(subscriber_key, queue)


@router.get("/runs/{run_id}/events", response_model=None)
async def stream_run_events(
    run_id: UUID,
    request: Request,
    run_repository: Annotated[RunRepository, Depends(get_run_repository)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> StreamingResponse | JSONResponse:
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
    broker = get_live_event_broker(request)
    return StreamingResponse(
        _stream_events(broker, run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
