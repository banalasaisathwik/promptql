"""Strict contracts for untrusted causal-hypothesis proposals and grounding."""

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints

from app.connectors.models import ContractModel, NonEmptyString
from app.investigations.models import FactSet, InvestigationIdentifier, MissingInformation


MAX_HYPOTHESES = 3
HypothesisRationale = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


class HypothesisKind(StrEnum):
    CODE_CHANGE_MAY_HAVE_CONTRIBUTED = "code_change_may_have_contributed"


class CandidateHypothesis(ContractModel):
    """A schema-valid proposal that is still untrusted until deterministic grounding."""

    hypothesis_id: InvestigationIdentifier
    kind: HypothesisKind
    subject: NonEmptyString
    supporting_fact_ids: Annotated[
        tuple[InvestigationIdentifier, ...], Field(min_length=1, max_length=10)
    ]
    contradicting_fact_ids: Annotated[
        tuple[InvestigationIdentifier, ...], Field(max_length=10)
    ] = ()
    rationale: HypothesisRationale | None = None


class HypothesisGenerationInput(ContractModel):
    """The minimized, fact-first state allowed to cross the LLM boundary."""

    investigation_goal: NonEmptyString
    facts: FactSet = ()
    missing_information: tuple[MissingInformation, ...] = Field(
        default=(), max_length=20
    )


class HypothesisGenerationOutput(ContractModel):
    candidates: Annotated[
        tuple[CandidateHypothesis, ...], Field(max_length=MAX_HYPOTHESES)
    ] = ()


class HypothesisGenerationMetadata(ContractModel):
    provider: NonEmptyString
    model: NonEmptyString
    prompt_id: NonEmptyString
    prompt_version: NonEmptyString


class GeneratedHypotheses(ContractModel):
    candidates: tuple[CandidateHypothesis, ...]
    metadata: HypothesisGenerationMetadata


class HypothesisGenerationFailureCode(StrEnum):
    PROVIDER_FAILURE = "provider_failure"
    INVALID_RESPONSE = "invalid_response"
    CANDIDATE_SCHEMA_INVALID = "candidate_schema_invalid"


class HypothesisValidationFailureCode(StrEnum):
    UNKNOWN_SUPPORTING_FACT = "unknown_supporting_fact"
    UNSUPPORTED_HYPOTHESIS_KIND = "unsupported_hypothesis_kind"
    ENTITY_MISMATCH = "entity_mismatch"
    MISSING_REQUIRED_SUPPORT = "missing_required_support"
    DUPLICATE_FACT_REFERENCE = "duplicate_fact_reference"


class RejectedHypothesis(ContractModel):
    candidate: CandidateHypothesis
    reason: HypothesisValidationFailureCode


class ValidatedHypothesis(ContractModel):
    hypothesis_id: InvestigationIdentifier
    kind: HypothesisKind
    subject: NonEmptyString
    supporting_fact_ids: tuple[InvestigationIdentifier, ...]


class HypothesisValidationResult(ContractModel):
    accepted_hypotheses: tuple[ValidatedHypothesis, ...] = ()
    rejected_candidates: tuple[RejectedHypothesis, ...] = ()
