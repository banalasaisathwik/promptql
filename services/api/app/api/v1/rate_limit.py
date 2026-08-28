import time
from collections.abc import Callable
from dataclasses import dataclass, field

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

DEFAULT_MAX_REQUESTS_PER_WINDOW = 10
DEFAULT_WINDOW_SECONDS = 60.0


RATE_LIMITED_PATHS = frozenset(
    {
        "/v1/investigations",
        "/v1/investigations/extract-grounding",
    }
)


@dataclass
class FixedWindowRateLimiter:
    max_requests: int = DEFAULT_MAX_REQUESTS_PER_WINDOW
    window_seconds: float = DEFAULT_WINDOW_SECONDS
    clock: Callable[[], float] = field(default=time.monotonic)
    _windows: dict[str, tuple[float, int]] = field(
        default_factory=dict, init=False, repr=False
    )

    def allow(self, client_key: str) -> bool:
        now = self.clock()
        window_start, count = self._windows.get(client_key, (now, 0))
        if now - window_start >= self.window_seconds:
            window_start, count = now, 0
        count += 1
        self._windows[client_key] = (window_start, count)
        return count <= self.max_requests


class PerIpRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, limiter: FixedWindowRateLimiter) -> None:
        super().__init__(app)
        self._limiter = limiter

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> JSONResponse:
        if request.url.path in RATE_LIMITED_PATHS:
            client_key = request.client.host if request.client else "unknown"
            if not self._limiter.allow(client_key):
                return JSONResponse(
                    status_code=429,
                    content={
                        "message": (
                            "Too many requests. Please wait a minute and try again."
                        )
                    },
                )
        return await call_next(request)
