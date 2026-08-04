pass

from enum import StrEnum

from app.connectors.models import ConnectorRequest


class GitHubErrorCategory(StrEnum):
    pass

    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    INVALID_RESPONSE = "invalid_response"
    CONFIGURATION_ERROR = "configuration_error"


class GitHubConnectorError(RuntimeError):
    pass

    category: GitHubErrorCategory

    def __init__(self, category: GitHubErrorCategory, message: str) -> None:
        self.category = category
        super().__init__(message)


class GitHubUnauthorizedError(GitHubConnectorError):
    def __init__(self) -> None:
        super().__init__(
            GitHubErrorCategory.UNAUTHORIZED,
            "GitHub authentication failed.",
        )


class GitHubForbiddenError(GitHubConnectorError):
    def __init__(self) -> None:
        super().__init__(
            GitHubErrorCategory.FORBIDDEN,
            "GitHub denied access to the requested operation.",
        )


class GitHubNotFoundError(GitHubConnectorError):
    def __init__(self) -> None:
        super().__init__(
            GitHubErrorCategory.NOT_FOUND,
            "The requested GitHub resource was not found.",
        )


class GitHubRateLimitedError(GitHubConnectorError):
    def __init__(self) -> None:
        super().__init__(
            GitHubErrorCategory.RATE_LIMITED,
            "GitHub rate limiting prevented the operation.",
        )


class GitHubTimeoutError(GitHubConnectorError):
    def __init__(self) -> None:
        super().__init__(
            GitHubErrorCategory.TIMEOUT,
            "The GitHub request timed out.",
        )


class GitHubUpstreamUnavailableError(GitHubConnectorError):
    def __init__(self) -> None:
        super().__init__(
            GitHubErrorCategory.UPSTREAM_UNAVAILABLE,
            "GitHub is currently unavailable.",
        )


class GitHubInvalidResponseError(GitHubConnectorError):
    def __init__(self) -> None:
        super().__init__(
            GitHubErrorCategory.INVALID_RESPONSE,
            "GitHub returned an invalid response.",
        )


class GitHubConfigurationError(GitHubConnectorError):
    def __init__(
        self,
        message: str = "GitHub connector configuration is invalid.",
    ) -> None:
        super().__init__(GitHubErrorCategory.CONFIGURATION_ERROR, message)


class ConnectorUnavailableError(RuntimeError):
    pass

    def __init__(self, connector_name: str) -> None:
        self.connector_name = connector_name
        super().__init__(f"{connector_name} connector is unavailable")


class FixtureNotFoundError(LookupError):
    pass

    def __init__(self, connector_name: str, request: ConnectorRequest) -> None:


        self.connector_name = connector_name
        self.request = request
        super().__init__(
            f"{connector_name} fixture not found for "
            f"{request.repository_owner}/{request.repository_name}"
            f"#{request.pr_number}"
        )
