from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from app.connectors.models import (
    ConnectorRequest,
    ConnectorSource,
    DeploymentEvidenceRequest,
    FailureLocationEvidenceRequest,
    GitHubCommitEvidenceRequest,
    GitHubPullRequest,
    GitHubPullRequestEvidenceRequest,
    IncidentEvidenceRequest,
    JiraIssue,
    TelemetryWindowEvidenceRequest,
)

if TYPE_CHECKING:
    from app.investigations.models import Evidence


class GitHubConnector(Protocol):
    source: ConnectorSource


    async def get_pull_request(
        self,
        request: ConnectorRequest,
    ) -> GitHubPullRequest: ...


class GitHubCodeEvidenceSource(Protocol):
    source: ConnectorSource

    async def get_commit_evidence(
        self,
        request: GitHubCommitEvidenceRequest,
    ) -> Evidence: ...

    async def get_pull_request_evidence(
        self,
        request: GitHubPullRequestEvidenceRequest,
    ) -> Evidence: ...

    async def get_changed_file_evidence(
        self,
        request: GitHubPullRequestEvidenceRequest,
    ) -> tuple[Evidence, ...]: ...


class IncidentSource(Protocol):
    source: ConnectorSource

    async def get_incident_evidence(
        self,
        request: IncidentEvidenceRequest,
    ) -> Evidence: ...

    async def get_deployment_evidence(
        self,
        request: DeploymentEvidenceRequest,
    ) -> Evidence: ...

    async def get_failure_location_evidence(
        self,
        request: FailureLocationEvidenceRequest,
    ) -> Evidence: ...

    async def get_telemetry_window_evidence(
        self,
        request: TelemetryWindowEvidenceRequest,
    ) -> Evidence: ...


class JiraConnector(Protocol):
    source: ConnectorSource


    async def get_issue(self, issue_key: str) -> JiraIssue: ...
