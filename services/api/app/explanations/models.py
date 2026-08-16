from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints

from app.connectors.models import ContractModel
from app.policy import (
    MergeReadinessDecision,
    PendingActionCode,
    PolicyReasonCode,
)


ExplanationText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
]


class LLMProviderName(StrEnum):
    FAKE = "fake"
    GEMINI = "gemini"
    GROQ = "groq"
    OPENAI = "openai"


class MergeReadinessExplanationInput(ContractModel):
    decision: MergeReadinessDecision
    primary_reason_code: PolicyReasonCode
    blocker_reason_codes: tuple[PolicyReasonCode, ...] = Field(max_length=50)
    missing_information_reason_codes: tuple[PolicyReasonCode, ...] = Field(
        max_length=50
    )
    pending_action_codes: tuple[PendingActionCode, ...] = Field(max_length=50)


class LLMTokenUsage(ContractModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class LLMStructuredResponse(ContractModel):
    output: object
    token_usage: LLMTokenUsage | None = None


class GeneratedExplanation(ContractModel):
    decision: MergeReadinessDecision
    summary: ExplanationText
    reason_codes: tuple[PolicyReasonCode, ...] = Field(
        min_length=1,
        max_length=50,
    )
    action_codes: tuple[PendingActionCode, ...] = Field(max_length=50)


class ValidatedExplanation(ContractModel):
    decision: MergeReadinessDecision
    reason_codes: tuple[PolicyReasonCode, ...] = Field(
        min_length=1,
        max_length=50,
    )
    action_codes: tuple[PendingActionCode, ...] = Field(max_length=50)


class MergeReadinessExplanation(ContractModel):
    decision: MergeReadinessDecision
    summary: ExplanationText
    reasons: tuple[ExplanationText, ...] = Field(max_length=50)
    recommended_actions: tuple[ExplanationText, ...] = Field(max_length=50)
