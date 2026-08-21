import os
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from urllib.parse import unquote, urlsplit

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from app.connectors.errors import GitHubConfigurationError, JiraConfigurationError


class DatabaseConfigurationError(RuntimeError):
    pass


class TelemetryConfigurationError(RuntimeError):
    pass


class GitHubConnectorMode(StrEnum):
    FAKE = "fake"
    GITHUB = "github"


class JiraConnectorMode(StrEnum):
    FAKE = "fake"
    JIRA = "jira"


class LLMProvider(StrEnum):
    FAKE = "fake"
    GEMINI = "gemini"
    GROQ = "groq"
    OPENAI = "openai"
    OPENROUTER = "openrouter"


class LLMTask(StrEnum):
    """Stable, deterministic names for the small set of model-owned workloads."""

    PLANNING = "planning"
    HYPOTHESIS_GENERATION = "hypothesis_generation"
    CODE_DIAGNOSIS = "code_diagnosis"


# PURPOSE: Map each bounded LLM task to configuration, without inspecting the
# request or introducing a probabilistic router.
#
# FLOW: Prefer the task-specific model -> fall back to the shared default -> fail
# startup when neither exists. The returned string is still only a requested
# model; the provider may report a separate resolved serving model.
@dataclass(frozen=True)
class ModelPolicy:
    """Resolve a configured model without interpreting request content."""

    default_model: str | None
    planner_model: str | None
    hypothesis_model: str | None
    code_diagnosis_model: str | None

    def model_for(self, task: LLMTask) -> str:
        task_model = {
            LLMTask.PLANNING: self.planner_model,
            LLMTask.HYPOTHESIS_GENERATION: self.hypothesis_model,
            LLMTask.CODE_DIAGNOSIS: self.code_diagnosis_model,
        }[task]
        model = task_model or self.default_model
        if model is None:
            raise LLMConfigurationError(
                f"No configured model is available for LLM task {task.value}."
            )
        return model


class LLMConfigurationError(RuntimeError):
    pass


def _parse_github_api_base_url(raw_url: str) -> str:
    url = raw_url.strip().rstrip("/")
    parsed_url = urlsplit(url)
    if (
        parsed_url.scheme != "https"
        or not parsed_url.hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise GitHubConfigurationError(
            "GITHUB_API_BASE_URL must be a credential-free HTTPS URL."
        )
    return url


def _parse_github_timeout(raw_timeout: str) -> float:
    try:
        timeout = float(raw_timeout)
    except ValueError:
        raise GitHubConfigurationError(
            "GITHUB_REQUEST_TIMEOUT_SECONDS must be a number."
        ) from None
    if not isfinite(timeout) or timeout <= 0 or timeout > 60:
        raise GitHubConfigurationError(
            "GITHUB_REQUEST_TIMEOUT_SECONDS must be greater than 0 and at most 60."
        )
    return timeout


def _parse_jira_base_url(raw_url: str) -> str:
    url = raw_url.strip().rstrip("/")
    parsed_url = urlsplit(url)
    hostname = (parsed_url.hostname or "").lower()
    if (
        parsed_url.scheme != "https"
        or not hostname.endswith(".atlassian.net")
        or hostname == "atlassian.net"
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.path not in {"", "/"}
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise JiraConfigurationError(
            "JIRA_BASE_URL must be a credential-free Jira Cloud HTTPS site URL."
        )
    return url


def _is_valid_jira_email(email: str | None) -> bool:
    if email is None or email.count("@") != 1:
        return False
    local_part, domain = email.split("@", 1)
    return bool(
        local_part
        and domain
        and not any(character.isspace() for character in email)
    )


def _parse_jira_timeout(raw_timeout: str) -> float:
    try:
        timeout = float(raw_timeout)
    except ValueError:
        raise JiraConfigurationError(
            "JIRA_REQUEST_TIMEOUT_SECONDS must be a number."
        ) from None
    if not isfinite(timeout) or timeout <= 0 or timeout > 60:
        raise JiraConfigurationError(
            "JIRA_REQUEST_TIMEOUT_SECONDS must be greater than 0 and at most 60."
        )
    return timeout


def _parse_llm_timeout(raw_timeout: str, variable_name: str) -> float:
    try:
        timeout = float(raw_timeout)
    except ValueError:
        raise LLMConfigurationError(
            f"{variable_name} must be a number."
        ) from None
    if not isfinite(timeout) or timeout <= 0 or timeout > 120:
        raise LLMConfigurationError(
            f"{variable_name} must be greater than 0 and at most 120."
        )
    return timeout


def _parse_llm_max_output_tokens(raw_value: str, variable_name: str) -> int:
    try:
        max_output_tokens = int(raw_value)
    except ValueError:
        raise LLMConfigurationError(
            f"{variable_name} must be an integer."
        ) from None
    if max_output_tokens < 1 or max_output_tokens > 4_096:
        raise LLMConfigurationError(
            f"{variable_name} must be between 1 and 4096."
        )
    return max_output_tokens


def _parse_boolean(raw_value: str, variable_name: str) -> bool:
    normalized_value = raw_value.strip().lower()
    if normalized_value in {"true", "1", "yes"}:
        return True
    if normalized_value in {"false", "0", "no", ""}:
        return False
    raise TelemetryConfigurationError(
        f"{variable_name} must be a boolean value."
    )


def _parse_otlp_headers(raw_headers: str) -> dict[str, str]:
    if not raw_headers.strip():
        return {}

    headers: dict[str, str] = {}
    for encoded_header in raw_headers.split(","):
        encoded_name, separator, encoded_value = encoded_header.partition("=")
        name = unquote(encoded_name).strip()
        value = unquote(encoded_value).strip()
        if not separator or not name or not value:
            raise TelemetryConfigurationError(
                "OTEL_EXPORTER_OTLP_HEADERS must contain name=value entries."
            )
        headers[name] = value
    return headers


def _validate_otlp_endpoint(raw_endpoint: str) -> str | None:
    endpoint = raw_endpoint.strip()
    if not endpoint:
        return None

    parsed_endpoint = urlsplit(endpoint)
    if (
        parsed_endpoint.scheme not in {"http", "https"}
        or not parsed_endpoint.hostname
        or parsed_endpoint.username is not None
        or parsed_endpoint.password is not None
    ):
        raise TelemetryConfigurationError(
            "OTEL_EXPORTER_OTLP_ENDPOINT must be a valid HTTP endpoint."
        )

    local_hosts = {"127.0.0.1", "localhost", "::1"}
    if (
        parsed_endpoint.scheme != "https"
        and parsed_endpoint.hostname not in local_hosts
    ):
        raise TelemetryConfigurationError(
            "Remote OTLP endpoints must use HTTPS."
        )
    return endpoint.rstrip("/")


def parse_postgresql_url(raw_url: str, variable_name: str) -> URL:
    if not raw_url.strip():
        raise DatabaseConfigurationError(f"{variable_name} is required.")

    try:
        url = make_url(raw_url)
    except ArgumentError:
        raise DatabaseConfigurationError(
            f"{variable_name} is not a valid database URL."
        ) from None

    if url.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise DatabaseConfigurationError(
            f"{variable_name} must use PostgreSQL with the psycopg driver."
        )
    if not url.host or not url.database or not url.username:
        raise DatabaseConfigurationError(
            f"{variable_name} must include a host, database, and username."
        )

    ssl_mode = url.query.get("sslmode")
    if ssl_mode not in {"require", "verify-ca", "verify-full"}:
        raise DatabaseConfigurationError(
            f"{variable_name} must require TLS with sslmode."
        )


    return url.set(drivername="postgresql+psycopg")


@dataclass(frozen=True)
class DatabaseSettings:
    database_url: URL

    @classmethod
    def from_environment(cls) -> "DatabaseSettings":
        return cls(
            database_url=parse_postgresql_url(
                os.environ.get("DATABASE_URL", ""),
                "DATABASE_URL",
            )
        )


@dataclass(frozen=True)
class GitHubSettings:
    mode: GitHubConnectorMode
    token: str | None = field(repr=False)
    api_base_url: str
    request_timeout_seconds: float

    @classmethod
    def from_environment(cls) -> "GitHubSettings":
        raw_mode = os.environ.get("PROMPTQL_GITHUB_CONNECTOR", "fake").strip()
        try:
            mode = GitHubConnectorMode(raw_mode)
        except ValueError:
            raise GitHubConfigurationError(
                "PROMPTQL_GITHUB_CONNECTOR must be fake or github."
            ) from None

        token = os.environ.get("GITHUB_TOKEN", "").strip() or None
        if mode is GitHubConnectorMode.GITHUB and token is None:
            raise GitHubConfigurationError(
                "GITHUB_TOKEN is required when the GitHub connector mode is github."
            )

        return cls(
            mode=mode,
            token=token,
            api_base_url=_parse_github_api_base_url(
                os.environ.get("GITHUB_API_BASE_URL", "https://api.github.com")
            ),
            request_timeout_seconds=_parse_github_timeout(
                os.environ.get("GITHUB_REQUEST_TIMEOUT_SECONDS", "10")
            ),
        )


@dataclass(frozen=True)
class JiraSettings:
    mode: JiraConnectorMode
    base_url: str | None
    email: str | None = field(repr=False)
    api_token: str | None = field(repr=False)
    request_timeout_seconds: float = 10

    @classmethod
    def from_environment(cls) -> "JiraSettings":
        raw_mode = os.environ.get("PROMPTQL_JIRA_CONNECTOR", "fake").strip()
        try:
            mode = JiraConnectorMode(raw_mode)
        except ValueError:
            raise JiraConfigurationError(
                "PROMPTQL_JIRA_CONNECTOR must be fake or jira."
            ) from None

        raw_base_url = os.environ.get("JIRA_BASE_URL", "").strip()
        email = os.environ.get("JIRA_EMAIL", "").strip() or None
        api_token = os.environ.get("JIRA_API_TOKEN", "").strip() or None
        if mode is JiraConnectorMode.JIRA:
            if not raw_base_url:
                raise JiraConfigurationError(
                    "JIRA_BASE_URL is required when the Jira connector mode is jira."
                )
            if not _is_valid_jira_email(email):
                raise JiraConfigurationError(
                    "JIRA_EMAIL must be a non-empty account email in Jira mode."
                )
            if api_token is None:
                raise JiraConfigurationError(
                    "JIRA_API_TOKEN is required when the Jira connector mode is jira."
                )

        return cls(
            mode=mode,
            base_url=(
                _parse_jira_base_url(raw_base_url)
                if raw_base_url
                else None
            ),
            email=email,
            api_token=api_token,
            request_timeout_seconds=_parse_jira_timeout(
                os.environ.get("JIRA_REQUEST_TIMEOUT_SECONDS", "10")
            ),
        )


@dataclass(frozen=True)
class LLMSettings:
    provider: LLMProvider
    api_key: str | None = field(repr=False)
    model: str | None
    request_timeout_seconds: float
    max_output_tokens: int
    model_policy: ModelPolicy | None = None

    def model_for(self, task: LLMTask) -> str:
        if self.model_policy is None:
            raise LLMConfigurationError("Fake LLM mode does not select configured models.")
        return self.model_policy.model_for(task)

    @classmethod
    def from_environment(cls) -> "LLMSettings":
        raw_provider = os.environ.get("PROMPTQL_LLM_PROVIDER", "fake").strip()
        try:
            provider = LLMProvider(raw_provider)
        except ValueError:
            raise LLMConfigurationError(
                "PROMPTQL_LLM_PROVIDER must be fake, gemini, groq, openai, or openrouter."
            ) from None

        if provider is LLMProvider.GEMINI:
            variable_prefix = "GEMINI"
        elif provider is LLMProvider.GROQ:
            variable_prefix = "GROQ"
        elif provider is LLMProvider.OPENROUTER:
            variable_prefix = "OPENROUTER"
        else:
            variable_prefix = "OPENAI"

        api_key = os.environ.get(f"{variable_prefix}_API_KEY", "").strip() or None
        # PROMPTQL_DEFAULT_MODEL is provider-neutral. The older provider-specific
        # setting remains a compatibility fallback for existing V1 deployments.
        model = (
            os.environ.get("PROMPTQL_DEFAULT_MODEL", "").strip()
            or os.environ.get(f"{variable_prefix}_MODEL", "").strip()
            or None
        )
        planner_model = os.environ.get("PROMPTQL_PLANNER_MODEL", "").strip() or None
        hypothesis_model = (
            os.environ.get("PROMPTQL_HYPOTHESIS_MODEL", "").strip() or None
        )
        code_diagnosis_model = (
            os.environ.get("PROMPTQL_CODE_DIAGNOSIS_MODEL", "").strip() or None
        )
        if provider is not LLMProvider.FAKE:
            if api_key is None:
                raise LLMConfigurationError(
                    f"{variable_prefix}_API_KEY is required when the LLM "
                    f"provider is {provider.value}."
                )
            if model is None and planner_model is None and hypothesis_model is None:
                raise LLMConfigurationError(
                    "PROMPTQL_DEFAULT_MODEL or a planning/hypothesis task model "
                    f"is required when the LLM provider is {provider.value}."
                )

        timeout_name = f"{variable_prefix}_REQUEST_TIMEOUT_SECONDS"
        token_limit_name = f"{variable_prefix}_MAX_OUTPUT_TOKENS"

        return cls(
            provider=provider,
            api_key=api_key,
            model=model,
            request_timeout_seconds=_parse_llm_timeout(
                os.environ.get(timeout_name, "30"),
                timeout_name,
            ),
            max_output_tokens=_parse_llm_max_output_tokens(
                os.environ.get(token_limit_name, "512"),
                token_limit_name,
            ),
            model_policy=(
                None
                if provider is LLMProvider.FAKE
                else ModelPolicy(
                    default_model=model,
                    planner_model=planner_model,
                    hypothesis_model=hypothesis_model,
                    code_diagnosis_model=code_diagnosis_model,
                )
            ),
        )


@dataclass(frozen=True)
class TelemetrySettings:
    enabled: bool
    console_enabled: bool
    service_name: str
    otlp_endpoint: str | None
    otlp_headers: dict[str, str]
    protocol: str

    @classmethod
    def from_environment(cls) -> "TelemetrySettings":
        enabled = _parse_boolean(
            os.environ.get("PROMPTQL_TELEMETRY_ENABLED", "false"),
            "PROMPTQL_TELEMETRY_ENABLED",
        )
        console_enabled = _parse_boolean(
            os.environ.get("PROMPTQL_TELEMETRY_CONSOLE_ENABLED", "false"),
            "PROMPTQL_TELEMETRY_CONSOLE_ENABLED",
        )
        service_name = os.environ.get("OTEL_SERVICE_NAME", "promptql-api").strip()
        protocol = os.environ.get(
            "OTEL_EXPORTER_OTLP_PROTOCOL",
            "http/protobuf",
        ).strip()

        if not service_name:
            raise TelemetryConfigurationError(
                "OTEL_SERVICE_NAME must not be empty."
            )
        if protocol != "http/protobuf":
            raise TelemetryConfigurationError(
                "OTEL_EXPORTER_OTLP_PROTOCOL must be http/protobuf."
            )

        endpoint = _validate_otlp_endpoint(
            os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        )
        headers = _parse_otlp_headers(
            os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")
        )
        if enabled and not console_enabled and endpoint is None:
            raise TelemetryConfigurationError(
                "Enabled telemetry requires a console or OTLP exporter."
            )

        return cls(
            enabled=enabled,
            console_enabled=console_enabled,
            service_name=service_name,
            otlp_endpoint=endpoint,
            otlp_headers=headers,
            protocol=protocol,
        )
