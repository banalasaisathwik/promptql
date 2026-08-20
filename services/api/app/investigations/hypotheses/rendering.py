"""Deterministic, Fact-grounded rendering for validated hypotheses."""

from enum import StrEnum

from app.connectors.models import ContractModel, NonEmptyString
from app.investigations.models import (
    ChangedFileFact,
    ChangedFileMatchesFailureFileFact,
    ChangedHunkOverlapsFailureLineFact,
    FactSet,
    InvestigationIdentifier,
    MissingInformation,
    MissingInformationKind,
)
from app.investigations.hypotheses.models import (
    HypothesisKind,
    ValidatedHypothesis,
)


class GroundedTerminationReason(StrEnum):
    COMPLETED = "completed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    NO_PROGRESS = "no_progress"
    PLANNING_LIMIT_REACHED = "planning_limit_reached"
    PROVIDER_FAILURE = "provider_failure"
    PLAN_VALIDATION_FAILURE = "plan_validation_failure"


class GroundedHypothesis(ContractModel):
    hypothesis_id: InvestigationIdentifier
    kind: HypothesisKind
    subject: NonEmptyString
    statement: NonEmptyString
    supporting_fact_ids: tuple[InvestigationIdentifier, ...]


class GroundedInvestigationResult(ContractModel):
    """The compact user-facing result produced from validated runtime state."""

    termination_reason: GroundedTerminationReason
    summary: NonEmptyString
    supported_hypotheses: tuple[GroundedHypothesis, ...] = ()
    key_fact_ids: tuple[InvestigationIdentifier, ...] = ()
    missing_information: tuple[MissingInformation, ...] = ()


class GroundingRenderError(ValueError):
    """Raised when a supposedly validated result violates its support boundary."""


def render_grounded_result(
    facts: FactSet,
    validated_hypotheses: tuple[ValidatedHypothesis, ...],
    missing_information: tuple[MissingInformation, ...],
    termination_reason: GroundedTerminationReason,
) -> GroundedInvestigationResult:
    # PURPOSE: Turn validated causal structure into the only final wording that
    # the investigation API and UI may expose.
    #
    # FLOW: Index typed Facts -> verify every accepted hypothesis reference ->
    # choose a fixed template -> return compact structured output. The candidate
    # rationale and any provider prose never enter this function.
    #
    # WHY: Deterministic rendering makes the same validated state produce the
    # same result and prevents a second unconstrained model call from adding an
    # unsupported causal claim.

    facts_by_id = {fact.fact_id: fact for fact in facts}
    rendered_hypotheses: list[GroundedHypothesis] = []
    key_fact_ids: list[str] = []

    for hypothesis in validated_hypotheses:
        if not isinstance(hypothesis, ValidatedHypothesis):
            raise GroundingRenderError("only validated hypotheses may be rendered")
        for fact_id in hypothesis.supporting_fact_ids:
            if fact_id not in facts_by_id:
                raise GroundingRenderError(
                    f"validated hypothesis references unknown Fact '{fact_id}'"
                )
            if fact_id not in key_fact_ids:
                key_fact_ids.append(fact_id)

        rendered_hypotheses.append(
            GroundedHypothesis(
                hypothesis_id=hypothesis.hypothesis_id,
                kind=hypothesis.kind,
                subject=hypothesis.subject,
                statement=_render_hypothesis_statement(hypothesis),
                supporting_fact_ids=hypothesis.supporting_fact_ids,
            )
        )

    summary = _render_summary(
        has_supported_hypothesis=bool(rendered_hypotheses),
        termination_reason=termination_reason,
    )

    return GroundedInvestigationResult(
        termination_reason=termination_reason,
        summary=summary,
        supported_hypotheses=tuple(rendered_hypotheses),
        key_fact_ids=tuple(key_fact_ids),
        missing_information=missing_information,
    )


def _render_hypothesis_statement(hypothesis: ValidatedHypothesis) -> str:
    if hypothesis.kind is HypothesisKind.CODE_CHANGE_MAY_HAVE_CONTRIBUTED:
        return f"Changes associated with {hypothesis.subject} may have contributed to the incident."
    raise GroundingRenderError(
        f"no deterministic renderer exists for hypothesis kind '{hypothesis.kind}'"
    )


def _render_summary(
    *,
    has_supported_hypothesis: bool,
    termination_reason: GroundedTerminationReason,
) -> str:
    conclusion = (
        "The investigation found a supported contributing factor."
        if has_supported_hypothesis
        else (
            "The investigation found relevant evidence, but it is not sufficient "
            "to support a causal hypothesis."
        )
    )
    prefixes = {
        GroundedTerminationReason.COMPLETED: "",
        GroundedTerminationReason.BUDGET_EXHAUSTED: (
            "The investigation stopped because the configured tool-call budget was exhausted. "
        ),
        GroundedTerminationReason.NO_PROGRESS: (
            "The investigation stopped because a planning round produced no new evidence or Facts. "
        ),
        GroundedTerminationReason.PLANNING_LIMIT_REACHED: (
            "The investigation stopped after reaching the configured planning-round limit. "
        ),
        GroundedTerminationReason.PROVIDER_FAILURE: (
            "Evidence collection completed, but structured hypothesis generation was unavailable. "
        ),
        GroundedTerminationReason.PLAN_VALIDATION_FAILURE: (
            "The investigation stopped because its execution plan could not be validated. "
        ),
    }
    return f"{prefixes[termination_reason]}{conclusion}"


def render_fact_summary(fact: object) -> str:
    """Return bounded detail for a Fact selected by a validated hypothesis."""

    if isinstance(fact, ChangedFileFact):
        return f"Changed file: {fact.path}."
    if isinstance(fact, ChangedFileMatchesFailureFileFact):
        return f"The changed file matches the observed failure location: {fact.file_path}."
    if isinstance(fact, ChangedHunkOverlapsFailureLineFact):
        return (
            f"The changed hunk overlaps the observed failure at "
            f"{fact.file_path}:{fact.line_number}."
        )
    return "Validated supporting evidence was recorded for this hypothesis."


def render_missing_information(item: MissingInformation) -> str:
    labels = {
        MissingInformationKind.DEPLOYMENT_MAPPING_UNAVAILABLE: "Deployment evidence was unavailable.",
        MissingInformationKind.INCIDENT_TIMELINE_INCOMPLETE: "The incident timeline was incomplete.",
        MissingInformationKind.SOURCE_DATA_UNAVAILABLE: "A required evidence source was unavailable.",
    }
    return item.detail or labels[item.kind]
