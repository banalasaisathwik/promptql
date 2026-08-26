import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.observability.live_event_broker import LiveEventBroker


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


@router.get("/runs/{run_id}/events")
async def stream_run_events(run_id: UUID, request: Request) -> StreamingResponse:
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
