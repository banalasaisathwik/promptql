from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Self

from pydantic import ConfigDict, ValidationError, model_validator

from app.connectors.models import (
    ContractModel,
    GitHubCommitEvidenceRequest,
    GitHubPullRequestEvidenceRequest,
    IncidentEvidenceRequest,
    DeploymentEvidenceRequest,
    TelemetryWindowEvidenceRequest,
    JiraIssueKey,
    NonEmptyString,
)
from app.investigations import Evidence


class InvestigationToolId(StrEnum):
    GET_COMMIT = "get_commit"
    GET_PULL_REQUEST = "get_pull_request"
    GET_DIFF = "get_diff"
    GET_INCIDENT = "get_incident"
    GET_DEPLOYMENTS = "get_deployments"
    QUERY_TELEMETRY = "query_telemetry"
    GET_JIRA_ISSUE = "get_jira_issue"


class ToolOutcome(StrEnum):
    OBSERVED = "observed"
    EMPTY = "empty"
    FAILED = "failed"


class ToolFailureCode(StrEnum):
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    SOURCE_FAILURE = "source_failure"


class ToolFailure(ContractModel):
    code: ToolFailureCode
    message: NonEmptyString


class ToolResult(ContractModel):
    tool_id: InvestigationToolId
    outcome: ToolOutcome
    evidence: tuple[Evidence, ...] = ()
    failure: ToolFailure | None = None

    @model_validator(mode="after")
    def validate_result_consistency(self) -> Self:
        if self.outcome is ToolOutcome.FAILED and self.failure is None:
            raise ValueError("failed tool results need a typed failure")
        if self.outcome is not ToolOutcome.FAILED and self.failure is not None:
            raise ValueError("only failed tool results may contain a failure")
        if self.outcome is ToolOutcome.OBSERVED and not self.evidence:
            raise ValueError("observed tool results need evidence")
        if self.outcome is ToolOutcome.EMPTY and self.evidence:
            raise ValueError("empty tool results cannot contain evidence")
        return self


class GetJiraIssueInput(ContractModel):
    issue_key: JiraIssueKey


ToolInputModel = (
    type[
        GitHubCommitEvidenceRequest
        | GitHubPullRequestEvidenceRequest
        | IncidentEvidenceRequest
        | DeploymentEvidenceRequest
        | TelemetryWindowEvidenceRequest
        | GetJiraIssueInput
    ]
)


class ToolDefinition(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        arbitrary_types_allowed=True,
    )

    tool_id: InvestigationToolId
    description: NonEmptyString
    input_model: ToolInputModel
    output_model: type[ToolResult]
    read_only: bool = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()

    def validate_arguments(self, arguments: Mapping[str, object]) -> ContractModel:
        try:
            return self.input_model.model_validate(arguments)
        except ValidationError as error:
            raise ValueError(f"invalid arguments for tool '{self.tool_id}'") from error


TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        tool_id=InvestigationToolId.GET_COMMIT,
        description="Retrieve normalized evidence for one Git commit.",
        input_model=GitHubCommitEvidenceRequest,
        output_model=ToolResult,
    ),
    ToolDefinition(
        tool_id=InvestigationToolId.GET_DEPLOYMENTS,
        description="Retrieve normalized evidence for one deployment.",
        input_model=DeploymentEvidenceRequest,
        output_model=ToolResult,
    ),
    ToolDefinition(
        tool_id=InvestigationToolId.GET_DIFF,
        description="Retrieve normalized changed-file and diff-hunk evidence for one pull request.",
        input_model=GitHubPullRequestEvidenceRequest,
        output_model=ToolResult,
    ),
    ToolDefinition(
        tool_id=InvestigationToolId.GET_INCIDENT,
        description="Retrieve normalized evidence for one engineering incident.",
        input_model=IncidentEvidenceRequest,
        output_model=ToolResult,
    ),
    ToolDefinition(
        tool_id=InvestigationToolId.GET_JIRA_ISSUE,
        description="Retrieve normalized evidence for one Jira issue.",
        input_model=GetJiraIssueInput,
        output_model=ToolResult,
    ),
    ToolDefinition(
        tool_id=InvestigationToolId.GET_PULL_REQUEST,
        description="Retrieve normalized evidence for one GitHub pull request.",
        input_model=GitHubPullRequestEvidenceRequest,
        output_model=ToolResult,
    ),
    ToolDefinition(
        tool_id=InvestigationToolId.QUERY_TELEMETRY,
        description="Retrieve bounded telemetry evidence for one service and time interval.",
        input_model=TelemetryWindowEvidenceRequest,
        output_model=ToolResult,
    ),
)
