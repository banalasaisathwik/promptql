from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.connectors.models import (
    ConnectorRequest,
    ConnectorSource,
    ContractModel,
    GitHubPullRequest,
    JiraIssue,
    NonEmptyString,
)
from app.policy.models import MergeReadinessResult


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowStepName(StrEnum):
    FETCH_GITHUB_FACTS = "fetch_github_facts"
    FETCH_JIRA_FACTS = "fetch_jira_facts"
    EVALUATE_MERGE_READINESS = "evaluate_merge_readiness"


class RuntimeErrorCode(StrEnum):
    CONNECTOR_EXECUTION_FAILED = "connector_execution_failed"
    POLICY_EXECUTION_FAILED = "policy_execution_failed"
    FIXTURE_NOT_FOUND = "fixture_not_found"


class RuntimeErrorInfo(ContractModel):
    code: RuntimeErrorCode
    message: NonEmptyString


class ExplanationSource(StrEnum):
    FAKE = "fake"
    GEMINI = "gemini"
    GROQ = "groq"
    OPENAI = "openai"


class RunSources(ContractModel):
    github: ConnectorSource | None
    jira: ConnectorSource | None
    explanation: ExplanationSource | None


class RuntimeStep(ContractModel):
    step_id: UUID
    name: WorkflowStepName
    status: StepStatus
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: Annotated[int, Field(strict=True, ge=0)] | None
    attempt: Annotated[int, Field(strict=True, gt=0)]
    error: RuntimeErrorInfo | None


    @model_validator(mode="after")
    def validate_lifecycle_fields(self) -> Self:
        if self.status is StepStatus.PENDING:
            if any(
                value is not None
                for value in (
                    self.started_at,
                    self.completed_at,
                    self.duration_ms,
                    self.error,
                )
            ):
                raise ValueError("a pending step cannot have execution metadata")
        elif self.status is StepStatus.RUNNING:
            if self.started_at is None or any(
                value is not None
                for value in (self.completed_at, self.duration_ms, self.error)
            ):
                raise ValueError("a running step needs only a start timestamp")
        else:
            if (
                self.started_at is None
                or self.completed_at is None
                or self.duration_ms is None
            ):
                raise ValueError("a terminal step needs complete timing metadata")
            if self.status is StepStatus.FAILED and self.error is None:
                raise ValueError("a failed step needs a structured error")
            if self.status is not StepStatus.FAILED and self.error is not None:
                raise ValueError("only a failed step may contain an error")
        return self


class MergeReadinessRun(ContractModel):
    run_id: UUID
    workflow_name: NonEmptyString
    workflow_version: NonEmptyString
    sources: RunSources | None = None
    status: RunStatus
    started_at: datetime | None
    completed_at: datetime | None
    steps: tuple[RuntimeStep, ...]
    error: RuntimeErrorInfo | None
    result: MergeReadinessResult | None
    request: ConnectorRequest
    github: GitHubPullRequest | None
    jira: JiraIssue | None


    @model_validator(mode="after")
    def validate_lifecycle_fields(self) -> Self:
        if self.status is RunStatus.PENDING:
            if any(
                value is not None
                for value in (
                    self.started_at,
                    self.completed_at,
                    self.error,
                    self.result,
                )
            ):
                raise ValueError("a pending run cannot have execution metadata")
        elif self.status is RunStatus.RUNNING:
            if self.started_at is None or any(
                value is not None
                for value in (self.completed_at, self.error, self.result)
            ):
                raise ValueError("a running run needs only a start timestamp")
        elif self.status is RunStatus.COMPLETED:
            if self.started_at is None or self.completed_at is None:
                raise ValueError("a completed run needs start and completion timestamps")
            if self.error is not None or self.result is None:
                raise ValueError("a completed run needs a result and no error")
        elif self.status is RunStatus.FAILED:
            if self.started_at is None or self.completed_at is None:
                raise ValueError("a failed run needs start and completion timestamps")
            if self.error is None or self.result is not None:
                raise ValueError("a failed run needs an error and a null result")
        elif self.status is RunStatus.CANCELLED:
            if self.started_at is None or self.completed_at is None:
                raise ValueError("a cancelled run needs start and completion timestamps")
            if self.result is not None:
                raise ValueError("a cancelled run cannot have a result")
        return self
