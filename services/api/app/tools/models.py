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
    SOURCE_FAILURE = "source_failure"


# PURPOSE: Carry a sanitized failure across the adapter/runtime boundary.
#
# FLOW: The adapter chooses one closed code from a connector error, then the
# executor reads `retryable` before deciding whether another provider call is
# permitted. Provider messages never participate in that control decision.
#
# DESIGN: This keeps retry policy deterministic and portable across providers,
# similar to using a discriminated union rather than matching exception strings.
class ToolFailure(ContractModel):
    code: ToolFailureCode
    message: NonEmptyString

    @property
    def retryable(self) -> bool:
        # Runtime retry policy is driven by a closed failure taxonomy, never by
        # an adapter message or a provider's untrusted response text.
        return self.code in {
            ToolFailureCode.RATE_LIMITED,
            ToolFailureCode.TIMEOUT,
            ToolFailureCode.UPSTREAM_UNAVAILABLE,
        }


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


class GetCommitPlanOutput(ContractModel):
    commit_sha: GitHubCommitEvidenceRequest.model_fields["commit_sha"].rebuild_annotation()


class GetDeploymentPlanOutput(ContractModel):
    deployment_reference: NonEmptyString
    service: NonEmptyString
    environment: NonEmptyString
    commit_sha: GitHubCommitEvidenceRequest.model_fields["commit_sha"].rebuild_annotation()


class GetDiffPlanOutput(ContractModel):
    pr_number: GitHubPullRequestEvidenceRequest.model_fields["pr_number"].rebuild_annotation()


class GetIncidentPlanOutput(ContractModel):
    incident_reference: NonEmptyString


class GetJiraIssuePlanOutput(ContractModel):
    issue_key: JiraIssueKey


class GetPullRequestPlanOutput(ContractModel):
    pr_number: GitHubPullRequestEvidenceRequest.model_fields["pr_number"].rebuild_annotation()
    base_sha: GitHubCommitEvidenceRequest.model_fields["commit_sha"].rebuild_annotation()
    head_sha: GitHubCommitEvidenceRequest.model_fields["commit_sha"].rebuild_annotation()


class QueryTelemetryPlanOutput(ContractModel):
    service: NonEmptyString


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
    # PURPOSE: Describe only values a future executor may expose to another plan
    # step. This static contract does not alter the V2.5 ToolResult runtime shape.
    plan_output_model: type[ContractModel]
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
        plan_output_model=GetCommitPlanOutput,
    ),
    ToolDefinition(
        tool_id=InvestigationToolId.GET_DEPLOYMENTS,
        description="Retrieve normalized evidence for one deployment.",
        input_model=DeploymentEvidenceRequest,
        output_model=ToolResult,
        plan_output_model=GetDeploymentPlanOutput,
    ),
    ToolDefinition(
        tool_id=InvestigationToolId.GET_DIFF,
        description="Retrieve normalized changed-file and diff-hunk evidence for one pull request.",
        input_model=GitHubPullRequestEvidenceRequest,
        output_model=ToolResult,
        plan_output_model=GetDiffPlanOutput,
    ),
    ToolDefinition(
        tool_id=InvestigationToolId.GET_INCIDENT,
        description="Retrieve normalized evidence for one engineering incident.",
        input_model=IncidentEvidenceRequest,
        output_model=ToolResult,
        plan_output_model=GetIncidentPlanOutput,
    ),
    ToolDefinition(
        tool_id=InvestigationToolId.GET_JIRA_ISSUE,
        description="Retrieve normalized evidence for one Jira issue.",
        input_model=GetJiraIssueInput,
        output_model=ToolResult,
        plan_output_model=GetJiraIssuePlanOutput,
    ),
    ToolDefinition(
        tool_id=InvestigationToolId.GET_PULL_REQUEST,
        description="Retrieve normalized evidence for one GitHub pull request.",
        input_model=GitHubPullRequestEvidenceRequest,
        output_model=ToolResult,
        plan_output_model=GetPullRequestPlanOutput,
    ),
    ToolDefinition(
        tool_id=InvestigationToolId.QUERY_TELEMETRY,
        description="Retrieve bounded telemetry evidence for one service and time interval.",
        input_model=TelemetryWindowEvidenceRequest,
        output_model=ToolResult,
        plan_output_model=QueryTelemetryPlanOutput,
    ),
)
