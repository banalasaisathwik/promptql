"""In-process fan-out of structured runtime events to live SSE subscribers.

This is a diagnostic tap, not an event-sourcing system: a browser that
subscribes late sees nothing that happened before it connected, and a slow
subscriber loses events rather than ever blocking the investigation task
that produced them. PostgreSQL remains the durable record of run state.
"""

import asyncio
from collections import defaultdict
from typing import Any


QUEUE_MAX_SIZE = 256


class LiveEventBroker:
    """Fan out structured events to per-run subscriber queues.

    Keyed by run_id as a string, matching how run identifiers already
    appear in a structured event record (StructuredEventLogger.emit()
    converts UUID fields to str before this broker ever sees them).
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = (
            defaultdict(list)
        )

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)
        self._subscribers[run_id].append(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        queues = self._subscribers.get(run_id)
        if queues is None:
            return
        try:
            queues.remove(queue)
        except ValueError:
            return
        if not queues:
            del self._subscribers[run_id]

    def publish(self, run_id: str, event: dict[str, Any]) -> None:
        for queue in self._subscribers.get(run_id, ()):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                continue
