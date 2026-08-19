from app.connectors.models import (
    BlockerState,
    CheckStatus,
    ConnectorRequest,
    DeploymentEvidenceRequest,
    FailureLocationEvidenceRequest,
    GitHubCommitEvidenceRequest,
    GitHubPullRequest,
    GitHubPullRequestEvidenceRequest,
    GitHubUser,
    IncidentEvidenceRequest,
    JiraAssignee,
    JiraIssue,
    JiraIssueStatus,
    Mergeability,
    PullRequestState,
    RequiredCheck,
    TelemetryFilter,
    TelemetrySignal,
    TelemetryWindowEvidenceRequest,
)
from app.connectors.errors import ConnectorUnavailableError, FixtureNotFoundError


__all__ = [
    "BlockerState",
    "CheckStatus",
    "ConnectorRequest",
    "DeploymentEvidenceRequest",
    "FailureLocationEvidenceRequest",
    "ConnectorUnavailableError",
    "FakeGitHubCodeEvidenceSource",
    "FakeGitHubConnector",
    "FakeIncidentSource",
    "FakeJiraConnector",
    "FixtureNotFoundError",
    "GitHubCommitEvidenceRequest",
    "GitHubPullRequest",
    "GitHubPullRequestEvidenceRequest",
    "GitHubUser",
    "IncidentEvidenceRequest",
    "JiraAssignee",
    "JiraIssue",
    "JiraIssueStatus",
    "Mergeability",
    "PullRequestState",
    "RequiredCheck",
    "TelemetryFilter",
    "TelemetrySignal",
    "TelemetryWindowEvidenceRequest",
]


def __getattr__(name: str):
    """Delay V2 fake imports so domain models can import connector contracts."""
    if name in {"FakeGitHubConnector", "FakeJiraConnector"}:
        from app.connectors.fakes import FakeGitHubConnector, FakeJiraConnector

        return {"FakeGitHubConnector": FakeGitHubConnector, "FakeJiraConnector": FakeJiraConnector}[name]
    if name == "FakeGitHubCodeEvidenceSource":
        from app.connectors.github_code_fakes import FakeGitHubCodeEvidenceSource

        return FakeGitHubCodeEvidenceSource
    if name == "FakeIncidentSource":
        from app.connectors.incident_fakes import FakeIncidentSource

        return FakeIncidentSource
    raise AttributeError(name)
"""Public import surface for V1 connector contracts and deterministic fakes.

Re-exporting supported types here gives callers one stable module to import from
while fixtures remain an implementation/testing concern in ``fixtures.py``.
"""
