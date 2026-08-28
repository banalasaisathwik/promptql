import httpx

from app.config import (
    GitHubConnectorMode,
    GitHubSettings,
    JiraConnectorMode,
    JiraSettings,
    SentryConnectorMode,
    SentrySettings,
)
from app.connectors.errors import (
    GitHubConfigurationError,
    JiraConfigurationError,
    SentryConfigurationError,
)
from app.connectors.fakes import FakeGitHubConnector, FakeJiraConnector
from app.connectors.github_code_fakes import FakeGitHubCodeEvidenceSource
from app.connectors.github_code_http import HttpGitHubCodeEvidenceSource
from app.connectors.github_http import HttpGitHubConnector
from app.connectors.incident_fakes import FakeIncidentSource
from app.connectors.jira_http import HttpJiraConnector
from app.connectors.protocols import (
    GitHubCodeEvidenceSource,
    GitHubConnector,
    IncidentSource,
    JiraConnector,
)
from app.connectors.sentry_http import HttpSentrySource
from app.observability import RuntimeTelemetry


def create_github_http_client(settings: GitHubSettings) -> httpx.AsyncClient:
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
    if settings.mode is GitHubConnectorMode.FAKE:
        return FakeGitHubConnector()
    if http_client is None:
        raise GitHubConfigurationError(
            "GitHub mode requires an application-scoped HTTP client."
        )
    return HttpGitHubConnector(http_client, telemetry)


def create_github_code_evidence_source(
    settings: GitHubSettings,
    telemetry: RuntimeTelemetry,
    http_client: httpx.AsyncClient | None = None,
) -> GitHubCodeEvidenceSource:
    if settings.mode is GitHubConnectorMode.FAKE:
        return FakeGitHubCodeEvidenceSource()
    if http_client is None:
        raise GitHubConfigurationError(
            "GitHub mode requires an application-scoped HTTP client."
        )
    return HttpGitHubCodeEvidenceSource(http_client, telemetry)


def create_jira_http_client(settings: JiraSettings) -> httpx.AsyncClient:
    if (
        settings.mode is not JiraConnectorMode.JIRA
        or settings.base_url is None
        or settings.email is None
        or settings.api_token is None
    ):
        raise JiraConfigurationError()
    timeout = settings.request_timeout_seconds
    return httpx.AsyncClient(
        base_url=settings.base_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "promptql-api",
        },
        auth=httpx.BasicAuth(settings.email, settings.api_token),
        timeout=httpx.Timeout(
            connect=timeout,
            read=timeout,
            write=timeout,
            pool=timeout,
        ),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        follow_redirects=False,
    )


def create_jira_connector(
    settings: JiraSettings,
    telemetry: RuntimeTelemetry,
    http_client: httpx.AsyncClient | None = None,
) -> JiraConnector:
    if settings.mode is JiraConnectorMode.FAKE:
        return FakeJiraConnector()
    if http_client is None:
        raise JiraConfigurationError(
            "Jira mode requires an application-scoped HTTP client."
        )
    return HttpJiraConnector(http_client, telemetry)


def create_sentry_http_client(settings: SentrySettings) -> httpx.AsyncClient:
    if settings.mode is not SentryConnectorMode.SENTRY or settings.token is None:
        raise SentryConfigurationError()
    return httpx.AsyncClient(
        base_url=settings.api_base_url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {settings.token}",
            "User-Agent": "promptql-api",
        },
        timeout=httpx.Timeout(settings.request_timeout_seconds),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        follow_redirects=False,
    )


def create_incident_source(
    settings: SentrySettings,
    telemetry: RuntimeTelemetry,
    http_client: httpx.AsyncClient | None = None,
) -> IncidentSource:
    if settings.mode is SentryConnectorMode.FAKE:
        return FakeIncidentSource()
    if http_client is None:
        raise SentryConfigurationError(
            "Sentry mode requires an application-scoped HTTP client."
        )
    if settings.organization_slug is None:
        raise SentryConfigurationError(
            "Sentry mode requires SENTRY_ORGANIZATION_SLUG."
        )
    return HttpSentrySource(http_client, settings.organization_slug, telemetry)
