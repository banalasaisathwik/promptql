from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

from app.connectors.errors import (
    ConnectorUnavailableError,
    FixtureNotFoundError,
    GitHubConnectorError,
    JiraConnectorError,
    SentryConnectorError,
)
from app.connectors.models import (
    DeploymentEvidenceRequest,
    GitHubCommitEvidenceRequest,
    GitHubPullRequestEvidenceRequest,
    IncidentEvidenceRequest,
    JiraIssue,
    TelemetryWindowEvidenceRequest,
)
from app.connectors.protocols import (
    GitHubCodeEvidenceSource,
    IncidentSource,
    JiraConnector,
)
from app.investigations import (
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
    EvidenceSource,
    JiraIssueEvidenceContent,
)
from app.investigations.evidence_store import EvidenceStore
from app.tools.errors import InvalidToolArgumentsError
from app.tools.models import (
    InvestigationToolId,
    TOOL_DEFINITIONS,
    ToolDefinition,
    ToolFailure,
    ToolFailureCode,
    ToolOutcome,
    ToolResult,
)


class InvestigationTool(Protocol):
    definition: ToolDefinition

    async def execute(self, arguments: Mapping[str, object]) -> ToolResult: ...


class _EvidenceTool:
    definition: ToolDefinition

    def __init__(self, store: EvidenceStore) -> None:
        self._store = store

    def _arguments(self, arguments: Mapping[str, object]):
        try:
            return self.definition.validate_arguments(arguments)
        except ValueError as error:
            raise InvalidToolArgumentsError(self.definition.tool_id) from error


    def _observed(self, evidence: Evidence | tuple[Evidence, ...]) -> ToolResult:
        evidence_items = evidence if isinstance(evidence, tuple) else (evidence,)
        evidence_ids = tuple(self._store.put(item) for item in evidence_items)
        return ToolResult(
            tool_id=self.definition.tool_id,
            outcome=ToolOutcome.OBSERVED,
            evidence_ids=evidence_ids,
        )


    def _failed(self, error: Exception) -> ToolResult:
        if isinstance(error, ConnectorUnavailableError):
            code = ToolFailureCode.CAPABILITY_UNAVAILABLE
            message = "the underlying capability is unavailable"
        elif isinstance(
            error,
            (GitHubConnectorError, JiraConnectorError, SentryConnectorError),
        ):
            code = ToolFailureCode(error.category.value)
            message = "the provider source failed to return evidence"
        elif isinstance(error, FixtureNotFoundError):
            code = ToolFailureCode.NOT_FOUND
            message = "the source did not return evidence for the request"
        else:
            raise error
        return ToolResult(
            tool_id=self.definition.tool_id,
            outcome=ToolOutcome.FAILED,
            failure=ToolFailure(code=code, message=message),
        )


class GetCommitTool(_EvidenceTool):
    definition = next(item for item in TOOL_DEFINITIONS if item.tool_id == InvestigationToolId.GET_COMMIT)

    def __init__(self, source: GitHubCodeEvidenceSource, store: EvidenceStore) -> None:
        super().__init__(store)
        self._source = source

    async def execute(self, arguments: Mapping[str, object]) -> ToolResult:
        request = self._arguments(arguments)
        try:
            return self._observed(await self._source.get_commit_evidence(request))
        except (ConnectorUnavailableError, FixtureNotFoundError, GitHubConnectorError) as error:
            return self._failed(error)


class GetPullRequestTool(_EvidenceTool):
    definition = next(item for item in TOOL_DEFINITIONS if item.tool_id == InvestigationToolId.GET_PULL_REQUEST)

    def __init__(self, source: GitHubCodeEvidenceSource, store: EvidenceStore) -> None:
        super().__init__(store)
        self._source = source

    async def execute(self, arguments: Mapping[str, object]) -> ToolResult:
        request = self._arguments(arguments)
        try:
            return self._observed(await self._source.get_pull_request_evidence(request))
        except (ConnectorUnavailableError, FixtureNotFoundError, GitHubConnectorError) as error:
            return self._failed(error)


class GetDiffTool(_EvidenceTool):
    definition = next(item for item in TOOL_DEFINITIONS if item.tool_id == InvestigationToolId.GET_DIFF)

    def __init__(self, source: GitHubCodeEvidenceSource, store: EvidenceStore) -> None:
        super().__init__(store)
        self._source = source

    async def execute(self, arguments: Mapping[str, object]) -> ToolResult:
        request = self._arguments(arguments)
        try:
            return self._observed(await self._source.get_changed_file_evidence(request))
        except (ConnectorUnavailableError, FixtureNotFoundError, GitHubConnectorError) as error:
            return self._failed(error)


class GetIncidentTool(_EvidenceTool):
    definition = next(item for item in TOOL_DEFINITIONS if item.tool_id == InvestigationToolId.GET_INCIDENT)

    def __init__(self, source: IncidentSource, store: EvidenceStore) -> None:
        super().__init__(store)
        self._source = source

    async def execute(self, arguments: Mapping[str, object]) -> ToolResult:
        request = self._arguments(arguments)
        try:
            return self._observed(await self._source.get_incident_evidence(request))
        except (
            ConnectorUnavailableError,
            FixtureNotFoundError,
            SentryConnectorError,
        ) as error:
            return self._failed(error)


class GetFailureLocationTool(_EvidenceTool):
    definition = next(
        item
        for item in TOOL_DEFINITIONS
        if item.tool_id == InvestigationToolId.GET_FAILURE_LOCATION
    )

    def __init__(self, source: IncidentSource, store: EvidenceStore) -> None:
        super().__init__(store)
        self._source = source

    async def execute(self, arguments: Mapping[str, object]) -> ToolResult:
        request = self._arguments(arguments)
        try:
            return self._observed(
                await self._source.get_failure_location_evidence(request)
            )
        except (
            ConnectorUnavailableError,
            FixtureNotFoundError,
            SentryConnectorError,
        ) as error:
            return self._failed(error)


class GetDeploymentsTool(_EvidenceTool):
    definition = next(item for item in TOOL_DEFINITIONS if item.tool_id == InvestigationToolId.GET_DEPLOYMENTS)

    def __init__(self, source: IncidentSource, store: EvidenceStore) -> None:
        super().__init__(store)
        self._source = source

    async def execute(self, arguments: Mapping[str, object]) -> ToolResult:
        request = self._arguments(arguments)
        try:
            return self._observed(await self._source.get_deployment_evidence(request))
        except (
            ConnectorUnavailableError,
            FixtureNotFoundError,
            SentryConnectorError,
        ) as error:
            return self._failed(error)


class QueryTelemetryTool(_EvidenceTool):
    definition = next(item for item in TOOL_DEFINITIONS if item.tool_id == InvestigationToolId.QUERY_TELEMETRY)

    def __init__(self, source: IncidentSource, store: EvidenceStore) -> None:
        super().__init__(store)
        self._source = source

    async def execute(self, arguments: Mapping[str, object]) -> ToolResult:
        request = self._arguments(arguments)
        try:
            return self._observed(await self._source.get_telemetry_window_evidence(request))
        except (
            ConnectorUnavailableError,
            FixtureNotFoundError,
            SentryConnectorError,
        ) as error:
            return self._failed(error)


class GetJiraIssueTool(_EvidenceTool):
    definition = next(item for item in TOOL_DEFINITIONS if item.tool_id == InvestigationToolId.GET_JIRA_ISSUE)

    def __init__(self, connector: JiraConnector, store: EvidenceStore) -> None:
        super().__init__(store)
        self._connector = connector

    async def execute(self, arguments: Mapping[str, object]) -> ToolResult:
        request = self._arguments(arguments)
        try:
            issue = await self._connector.get_issue(request.issue_key)
            return self._observed(self._to_evidence(issue))
        except (ConnectorUnavailableError, FixtureNotFoundError, JiraConnectorError) as error:
            return self._failed(error)

    @staticmethod
    def _to_evidence(issue: JiraIssue) -> Evidence:
        retrieved_at = datetime.now(UTC)
        return Evidence(
            evidence_id=f"jira:{issue.issue_key}",
            source=EvidenceSource.JIRA,
            kind=EvidenceKind.JIRA_ISSUE,
            provenance=EvidenceProvenance(
                source_reference=f"jira:{issue.issue_key}",
                retrieved_at=retrieved_at,
            ),
            content=JiraIssueEvidenceContent(
                issue_key=issue.issue_key,
                status=issue.status,
            ),
        )


def build_tool_registry(tools: Mapping[str, InvestigationTool]) -> "ToolRegistry":
    from app.tools.registry import ToolRegistry

    registry = ToolRegistry()
    for tool in tools.values():
        registry.register(tool.definition)
    return registry


def build_tool_adapters(
    github_source: GitHubCodeEvidenceSource,
    incident_source: IncidentSource,
    jira_connector: JiraConnector,
    store: EvidenceStore,
) -> dict[str, InvestigationTool]:
    tools: tuple[InvestigationTool, ...] = (
        GetCommitTool(github_source, store),
        GetPullRequestTool(github_source, store),
        GetDiffTool(github_source, store),
        GetFailureLocationTool(incident_source, store),
        GetIncidentTool(incident_source, store),
        GetDeploymentsTool(incident_source, store),
        QueryTelemetryTool(incident_source, store),
        GetJiraIssueTool(jira_connector, store),
    )
    return {tool.definition.tool_id: tool for tool in tools}
