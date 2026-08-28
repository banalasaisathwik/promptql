import unittest

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.api.v1.rate_limit import FixedWindowRateLimiter, PerIpRateLimitMiddleware


class FixedWindowRateLimiterTests(unittest.TestCase):
    def test_allows_requests_up_to_the_configured_maximum(self) -> None:
        clock = _FakeClock(start=0.0)
        limiter = FixedWindowRateLimiter(
            max_requests=3, window_seconds=60.0, clock=clock
        )

        results = [limiter.allow("1.1.1.1") for _ in range(3)]

        self.assertEqual(results, [True, True, True])

    def test_rejects_requests_beyond_the_maximum_within_the_window(self) -> None:
        clock = _FakeClock(start=0.0)
        limiter = FixedWindowRateLimiter(
            max_requests=3, window_seconds=60.0, clock=clock
        )
        for _ in range(3):
            limiter.allow("1.1.1.1")

        self.assertFalse(limiter.allow("1.1.1.1"))

    def test_resets_after_the_window_elapses(self) -> None:
        clock = _FakeClock(start=0.0)
        limiter = FixedWindowRateLimiter(
            max_requests=2, window_seconds=60.0, clock=clock
        )
        limiter.allow("1.1.1.1")
        limiter.allow("1.1.1.1")
        self.assertFalse(limiter.allow("1.1.1.1"))

        clock.advance(60.0)

        self.assertTrue(limiter.allow("1.1.1.1"))

    def test_tracks_separate_clients_independently(self) -> None:
        clock = _FakeClock(start=0.0)
        limiter = FixedWindowRateLimiter(
            max_requests=1, window_seconds=60.0, clock=clock
        )
        self.assertTrue(limiter.allow("1.1.1.1"))
        self.assertFalse(limiter.allow("1.1.1.1"))

        self.assertTrue(limiter.allow("2.2.2.2"))


async def _limited_endpoint(_request) -> JSONResponse:
    return JSONResponse({"ok": True})


class PerIpRateLimitMiddlewareTests(unittest.TestCase):
    def _build_client(self, limiter: FixedWindowRateLimiter) -> TestClient:
        app = Starlette(
            routes=[
                Route(
                    "/v1/investigations",
                    _limited_endpoint,
                    methods=["POST"],
                ),
                Route(
                    "/v1/runs/some-id",
                    _limited_endpoint,
                    methods=["GET"],
                ),
            ]
        )
        app.add_middleware(PerIpRateLimitMiddleware, limiter=limiter)
        return TestClient(app)

    def test_returns_429_once_the_limit_is_exceeded(self) -> None:
        clock = _FakeClock(start=0.0)
        limiter = FixedWindowRateLimiter(
            max_requests=2, window_seconds=60.0, clock=clock
        )
        client = self._build_client(limiter)

        first = client.post("/v1/investigations")
        second = client.post("/v1/investigations")
        third = client.post("/v1/investigations")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(third.status_code, 429)
        self.assertIn("Too many requests", third.json()["message"])

    def test_allows_requests_again_after_the_window_resets(self) -> None:
        clock = _FakeClock(start=0.0)
        limiter = FixedWindowRateLimiter(
            max_requests=1, window_seconds=60.0, clock=clock
        )
        client = self._build_client(limiter)

        client.post("/v1/investigations")
        blocked = client.post("/v1/investigations")
        clock.advance(60.0)
        recovered = client.post("/v1/investigations")

        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(recovered.status_code, 200)

    def test_does_not_limit_paths_outside_the_configured_set(self) -> None:
        clock = _FakeClock(start=0.0)
        limiter = FixedWindowRateLimiter(
            max_requests=1, window_seconds=60.0, clock=clock
        )
        client = self._build_client(limiter)

        client.get("/v1/runs/some-id")
        second = client.get("/v1/runs/some-id")

        self.assertEqual(second.status_code, 200)


class _FakeClock:
    def __init__(self, start: float) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


if __name__ == "__main__":
    unittest.main()
