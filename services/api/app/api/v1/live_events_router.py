"""Server-Sent Events stream of live structured runtime events for one run.

This is a diagnostic tap on events that already exist (see
app/observability/live_event_broker.py), not a durable event log: a
browser that connects late sees nothing that happened before it
connected, and the stream carries no historical replay. The existing
polling endpoint (`GET /v1/runs/{run_id}`) remains the source of the
durable, persisted run snapshot.
"""

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
    # No manual disconnect check here: Starlette's StreamingResponse already
    # runs a concurrent task that listens for client disconnect and cancels
    # this generator when it happens (the `finally` below still runs on that
    # cancellation). Calling request.is_disconnected() from inside the body
    # generator too would be a second concurrent reader of the same ASGI
    # receive channel and deadlocks against Starlette's own listener.
    subscriber_key = str(run_id)
    queue = broker.subscribe(subscriber_key)
    try:
        while True:
            try:
                event = await asyncio.wait_for(
                    queue.get(), timeout=poll_interval_seconds
                )
            except asyncio.TimeoutError:
                # A comment line keeps intermediaries (proxies, browsers)
                # from timing out an idle SSE connection; it is ignored by
                # EventSource clients since it carries no "data:" field.
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
