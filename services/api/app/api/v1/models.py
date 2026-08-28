from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import model_validator

from app.connectors.models import ContractModel, NonEmptyString
from app.explanations import ExplanationErrorCode, MergeReadinessExplanation
from app.investigations.grounding_extraction import GroundingExtractionOutput
from app.runtime import MergeReadinessRun, RunStatus
from app.runtime.investigation_models import InvestigationRun


class ApiErrorCode(StrEnum):
    FIXTURE_NOT_FOUND = "fixture_not_found"
    RUN_NOT_FOUND = "run_not_found"
    RUNTIME_PERSISTENCE_UNAVAILABLE = "runtime_persistence_unavailable"
    RUNTIME_STATE_CONFLICT = "runtime_state_conflict"
    RUNTIME_RECORD_INVALID = "runtime_record_invalid"


class ApiError(ContractModel):
    code: ApiErrorCode
    message: NonEmptyString


class RuntimePersistenceApiError(ApiError):
    run_id: UUID | None


class LiveRunStartResponse(ContractModel):
    run_id: UUID
    status: RunStatus

    @model_validator(mode="after")
    def validate_pending_status(self) -> Self:
        if self.status is not RunStatus.PENDING:
            raise ValueError("a newly accepted live run must be pending")
        return self


class ExplanationApiError(ContractModel):
    code: ExplanationErrorCode
    message: NonEmptyString


class MergeReadinessResponse(MergeReadinessRun):
    explanation: MergeReadinessExplanation | None
    explanation_error: ExplanationApiError | None

    @model_validator(mode="after")
    def validate_explanation_state(self) -> Self:
        if self.status is not RunStatus.COMPLETED:
            if self.explanation is not None or self.explanation_error is not None:
                raise ValueError("only a completed run may have an explanation")
            return self

        has_explanation = self.explanation is not None
        has_error = self.explanation_error is not None
        if has_explanation == has_error:
            raise ValueError(
                "a completed run needs either an explanation or an explanation error"
            )
        if (
            self.explanation is not None
            and self.result is not None
            and self.explanation.decision is not self.result.decision
        ):
            raise ValueError("the explanation cannot change the policy decision")
        return self


class InvestigationResponse(InvestigationRun):
    pass


class FollowUpInvestigationRequest(ContractModel):
    question: NonEmptyString


class InvestigationFollowUpStartResponse(ContractModel):
    run_id: UUID
    status: RunStatus

    @model_validator(mode="after")
    def validate_running_status(self) -> Self:
        if self.status is not RunStatus.RUNNING:
            raise ValueError("a newly accepted follow-up run must be running")
        return self


class GroundingExtractionStatus(StrEnum):
    COMPLETE = "complete"
    NEEDS_CLARIFICATION = "needs_clarification"


class MissingGroundingField(StrEnum):
    INCIDENT_REFERENCE = "incident_reference"
    DEPLOYMENT_REFERENCE = "deployment_reference"
    PULL_REQUEST_NUMBER = "pull_request_number"


class GroundingExtractionApiErrorCode(StrEnum):
    PROVIDER_FAILURE = "provider_failure"
    INVALID_RESPONSE = "invalid_response"
    EXTRACTION_SCHEMA_INVALID = "extraction_schema_invalid"


class GroundingExtractionApiError(ContractModel):
    code: GroundingExtractionApiErrorCode
    message: NonEmptyString


class GroundingExtractionResponse(ContractModel):
    status: GroundingExtractionStatus
    extracted: GroundingExtractionOutput
    missing: tuple[MissingGroundingField, ...] = ()
    question: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_status_consistency(self) -> Self:
        if self.status is GroundingExtractionStatus.COMPLETE:
            if self.missing or self.question is not None:
                raise ValueError(
                    "a complete extraction must not report missing fields or a question"
                )
        else:
            if not self.missing or self.question is None:
                raise ValueError(
                    "an incomplete extraction must report missing fields and a "
                    "clarifying question"
                )
        return self
