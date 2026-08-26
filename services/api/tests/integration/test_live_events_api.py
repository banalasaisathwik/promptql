import unittest
from uuid import uuid4

from app.main import app


class LiveEventsApiTests(unittest.TestCase):
    def test_the_sse_route_is_registered_on_the_application(self) -> None:
        # This endpoint streams indefinitely by design, so it cannot be
        # driven end-to-end through httpx's ASGI test transports: both
        # TestClient and a raw httpx.AsyncClient(transport=ASGITransport(...))
        # collect the full ASGI response before returning it to the caller,
        # which never happens for a stream with no natural end. The
        # generator's own behavior (subscribe, deliver, unsubscribe on
        # cancellation) is covered directly in
        # tests/unit/test_live_events_router.py; this only confirms main.py
        # actually wired the router onto the application, using FastAPI's
        # public URL-resolution API rather than the routing internals.
        run_id = uuid4()

        resolved_path = app.url_path_for("stream_run_events", run_id=str(run_id))

        self.assertEqual(resolved_path, f"/v1/runs/{run_id}/events")


if __name__ == "__main__":
    unittest.main()
