from enum import StrEnum

from app.connectors.models import ConnectorRequest


class ConnectorErrorCategory(StrEnum):
    INVALID_REQUEST = "invalid_request"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    INVALID_RESPONSE = "invalid_response"
    INCOMPLETE_RESULT = "incomplete_result"
    CONFIGURATION_ERROR = "configuration_error"


GitHubErrorCategory = ConnectorErrorCategory


class GitHubConnectorError(RuntimeError):
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


class GitHubIncompleteResultError(GitHubConnectorError):
    def __init__(self) -> None:
        super().__init__(
            GitHubErrorCategory.INCOMPLETE_RESULT,
            "GitHub could not provide a complete bounded result.",
        )


class GitHubConfigurationError(GitHubConnectorError):
    def __init__(
        self,
        message: str = "GitHub connector configuration is invalid.",
    ) -> None:
        super().__init__(GitHubErrorCategory.CONFIGURATION_ERROR, message)


class JiraConnectorError(RuntimeError):
    category: ConnectorErrorCategory

    def __init__(self, category: ConnectorErrorCategory, message: str) -> None:
        self.category = category
        super().__init__(message)


class JiraInvalidIssueKeyError(JiraConnectorError):
    def __init__(self) -> None:
        super().__init__(
            ConnectorErrorCategory.INVALID_REQUEST,
            "The Jira issue key is invalid.",
        )


class JiraUnauthorizedError(JiraConnectorError):
    def __init__(self) -> None:
        super().__init__(
            ConnectorErrorCategory.UNAUTHORIZED,
            "Jira authentication failed.",
        )


class JiraForbiddenError(JiraConnectorError):
    def __init__(self) -> None:
        super().__init__(
            ConnectorErrorCategory.FORBIDDEN,
            "Jira denied access to the requested operation.",
        )


class JiraIssueUnavailableError(JiraConnectorError):
    def __init__(self) -> None:
        super().__init__(
            ConnectorErrorCategory.NOT_FOUND,
            "The Jira issue is unavailable or was not found.",
        )


class JiraRateLimitedError(JiraConnectorError):
    def __init__(self, retry_after_seconds: int | None = None) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            ConnectorErrorCategory.RATE_LIMITED,
            "Jira rate limiting prevented the operation.",
        )


class JiraTimeoutError(JiraConnectorError):
    def __init__(self) -> None:
        super().__init__(
            ConnectorErrorCategory.TIMEOUT,
            "The Jira request timed out.",
        )


class JiraUpstreamUnavailableError(JiraConnectorError):
    def __init__(self) -> None:
        super().__init__(
            ConnectorErrorCategory.UPSTREAM_UNAVAILABLE,
            "Jira is currently unavailable.",
        )


class JiraInvalidResponseError(JiraConnectorError):
    def __init__(self) -> None:
        super().__init__(
            ConnectorErrorCategory.INVALID_RESPONSE,
            "Jira returned an invalid response.",
        )


class JiraConfigurationError(JiraConnectorError):
    def __init__(
        self,
        message: str = "Jira connector configuration is invalid.",
    ) -> None:
        super().__init__(ConnectorErrorCategory.CONFIGURATION_ERROR, message)


class ConnectorUnavailableError(RuntimeError):
    def __init__(self, connector_name: str) -> None:
        self.connector_name = connector_name
        super().__init__(f"{connector_name} connector is unavailable")


class FixtureNotFoundError(LookupError):
    def __init__(
        self,
        connector_name: str,
        request: ConnectorRequest | None = None,
    ) -> None:
        self.connector_name = connector_name
        self.request = request
        message = f"{connector_name} fixture not found"
        if request is not None:
            message += (
                f" for {request.repository_owner}/{request.repository_name}"
                f"#{request.pr_number}"
            )
        super().__init__(message)
