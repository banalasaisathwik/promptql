import unittest
from uuid import uuid4

from app.main import app


class LiveEventsApiTests(unittest.TestCase):
    def test_the_sse_route_is_registered_on_the_application(self) -> None:
        run_id = uuid4()

        resolved_path = app.url_path_for("stream_run_events", run_id=str(run_id))

        self.assertEqual(resolved_path, f"/v1/runs/{run_id}/events")


if __name__ == "__main__":
    unittest.main()
