pass

import httpx

from app.config import GitHubConnectorMode, GitHubSettings
from app.connectors.errors import GitHubConfigurationError
from app.connectors.fakes import FakeGitHubConnector
from app.connectors.github_http import HttpGitHubConnector
from app.connectors.protocols import GitHubConnector
from app.observability import RuntimeTelemetry


def create_github_http_client(settings: GitHubSettings) -> httpx.AsyncClient:
    pass

    if settings.mode is not GitHubConnectorMode.GITHUB or settings.token is None:
        raise GitHubConfigurationError()
    return httpx.AsyncClient(
        base_url=settings.api_base_url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {settings.token}",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "promptql-api",
        },
        timeout=httpx.Timeout(settings.request_timeout_seconds),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        follow_redirects=False,
    )


def create_github_connector(
    settings: GitHubSettings,
    telemetry: RuntimeTelemetry,
    http_client: httpx.AsyncClient | None = None,
) -> GitHubConnector:
    pass

    if settings.mode is GitHubConnectorMode.FAKE:
        return FakeGitHubConnector()
    if http_client is None:
        raise GitHubConfigurationError(
            "GitHub mode requires an application-scoped HTTP client."
        )
    return HttpGitHubConnector(http_client, telemetry)
