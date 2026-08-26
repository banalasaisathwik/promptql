"""Deterministic, Fact-grounded rendering for validated hypotheses."""

from enum import StrEnum

from app.connectors.models import ContractModel, NonEmptyString
from app.investigations.code_diagnosis.models import (
    CodeFindingCategory,
    DeveloperRecommendation,
    ValidatedCodeFinding,
)
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
    PLANNER_FAILURE = "planner_failure"
    HYPOTHESIS_GENERATION_FAILURE = "hypothesis_generation_failure"
    CODE_DIAGNOSIS_FAILURE = "code_diagnosis_failure"
    # Older V2.19 JSON snapshots used this broader value. Retaining it keeps
    # persisted runs readable while new runs record the precise failed stage.
    PROVIDER_FAILURE = "provider_failure"
    PLAN_VALIDATION_FAILURE = "plan_validation_failure"


class GroundedHypothesis(ContractModel):
    hypothesis_id: InvestigationIdentifier
    kind: HypothesisKind
    subject: NonEmptyString
    statement: NonEmptyString
    supporting_fact_ids: tuple[InvestigationIdentifier, ...]


class GroundedCodeFinding(ContractModel):
    finding_id: InvestigationIdentifier
    hypothesis_id: InvestigationIdentifier
    category: CodeFindingCategory
    file_path: NonEmptyString
    line_number: int | None = None
    function_name: NonEmptyString | None = None
    hunk_evidence_id: InvestigationIdentifier | None = None
    statement: NonEmptyString
    supporting_fact_ids: tuple[InvestigationIdentifier, ...]
    supporting_evidence_ids: tuple[InvestigationIdentifier, ...]


class GroundedInvestigationResult(ContractModel):
    """The compact user-facing result produced from validated runtime state."""

    termination_reason: GroundedTerminationReason
    summary: NonEmptyString
    supported_hypotheses: tuple[GroundedHypothesis, ...] = ()
    code_findings: tuple[GroundedCodeFinding, ...] = ()
    recommendations: tuple[DeveloperRecommendation, ...] = ()
    key_fact_ids: tuple[InvestigationIdentifier, ...] = ()
    missing_information: tuple[MissingInformation, ...] = ()


class GroundingRenderError(ValueError):
    """Raised when a supposedly validated result violates its support boundary."""


def render_grounded_result(
    facts: FactSet,
    validated_hypotheses: tuple[ValidatedHypothesis, ...],
    missing_information: tuple[MissingInformation, ...],
    termination_reason: GroundedTerminationReason,
    validated_code_findings: tuple[ValidatedCodeFinding, ...] = (),
    recommendations: tuple[DeveloperRecommendation, ...] = (),
    evidence: tuple[InvestigationIdentifier, ...] = (),
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
        has_evidence=bool(evidence) or bool(facts),
        termination_reason=termination_reason,
    )
    rendered_code_findings = _render_code_findings(
        validated_code_findings,
        validated_hypotheses,
        facts_by_id,
    )
    _validate_recommendations(recommendations, validated_code_findings)

    return GroundedInvestigationResult(
        termination_reason=termination_reason,
        summary=summary,
        supported_hypotheses=tuple(rendered_hypotheses),
        code_findings=rendered_code_findings,
        recommendations=recommendations,
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
    has_evidence: bool,
    termination_reason: GroundedTerminationReason,
) -> str:
    if has_supported_hypothesis:
        conclusion = "The investigation found a supported contributing factor."
    elif has_evidence:
        conclusion = (
            "The investigation found relevant evidence, but it is not sufficient "
            "to support a causal hypothesis."
        )
    else:
        # A run can terminate (e.g. plan_validation_failure on round 1) before
        # any evidence is ever collected. The general "found relevant evidence"
        # conclusion would misrepresent that as an evaluated-and-insufficient
        # outcome rather than a run that never got to evaluate anything.
        conclusion = (
            "The investigation could not proceed far enough to collect evidence."
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
        GroundedTerminationReason.PLANNER_FAILURE: (
            "Evidence collection stopped because structured planning was unavailable. "
        ),
        GroundedTerminationReason.HYPOTHESIS_GENERATION_FAILURE: (
            "Evidence collection completed, but structured hypothesis generation was unavailable. "
        ),
        GroundedTerminationReason.CODE_DIAGNOSIS_FAILURE: (
            "A causal hypothesis was grounded, but structured code diagnosis was unavailable. "
        ),
        # This branch renders historical snapshots only; current workflow code
        # selects PLANNER_FAILURE or HYPOTHESIS_GENERATION_FAILURE instead.
        GroundedTerminationReason.PROVIDER_FAILURE: (
            "The investigation could not complete because a configured model provider was unavailable. "
        ),
        GroundedTerminationReason.PLAN_VALIDATION_FAILURE: (
            "The investigation stopped because its execution plan could not be validated. "
        ),
    }
    return f"{prefixes[termination_reason]}{conclusion}"


def _render_code_findings(
    findings: tuple[ValidatedCodeFinding, ...],
    hypotheses: tuple[ValidatedHypothesis, ...],
    facts_by_id: dict[str, object],
) -> tuple[GroundedCodeFinding, ...]:
    # PURPOSE: Cross the final presentation boundary using only accepted domain
    # values. The LLM's explanation field is intentionally no longer available.
    hypothesis_ids = {item.hypothesis_id for item in hypotheses}
    rendered: list[GroundedCodeFinding] = []
    for finding in findings:
        if not isinstance(finding, ValidatedCodeFinding):
            raise GroundingRenderError("only validated code findings may be rendered")
        if finding.hypothesis_id not in hypothesis_ids:
            raise GroundingRenderError("code finding references an unknown validated hypothesis")
        if not set(finding.supporting_fact_ids) <= set(facts_by_id):
            raise GroundingRenderError("code finding references an unknown Fact")
        rendered.append(
            GroundedCodeFinding(
                finding_id=finding.finding_id,
                hypothesis_id=finding.hypothesis_id,
                category=finding.category,
                file_path=finding.file_path,
                line_number=finding.line_number,
                function_name=finding.function_name,
                hunk_evidence_id=finding.hunk_evidence_id,
                statement=_render_code_finding_statement(finding),
                supporting_fact_ids=finding.supporting_fact_ids,
                supporting_evidence_ids=finding.supporting_evidence_ids,
            )
        )
    return tuple(rendered)


def _render_code_finding_statement(finding: ValidatedCodeFinding) -> str:
    labels = {
        CodeFindingCategory.CHANGED_CODE_NEAR_FAILURE: "changed code near the observed failure",
        CodeFindingCategory.ERROR_HANDLING_OR_NULL_PATH: "an error-handling or null path",
        CodeFindingCategory.INPUT_VALIDATION: "an input-validation path",
        CodeFindingCategory.STATE_OR_RESOURCE_LIFECYCLE: "a state or resource-lifecycle path",
        CodeFindingCategory.CONFIGURATION_OR_DEPLOYMENT: "a configuration or deployment path",
    }
    location = finding.file_path
    if finding.function_name is not None:
        location = f"{location} in {finding.function_name}"
    if finding.line_number is not None:
        location = f"{location} at line {finding.line_number}"
    return f"The Evidence identifies {labels[finding.category]} at {location} as a suspected contributor."


def _validate_recommendations(
    recommendations: tuple[DeveloperRecommendation, ...],
    findings: tuple[ValidatedCodeFinding, ...],
) -> None:
    # WATCH OUT: A recommendation is safe wording, but its references still
    # must belong to the exact finding that caused the template to be selected.
    findings_by_id = {item.finding_id: item for item in findings}
    for recommendation in recommendations:
        finding = findings_by_id.get(recommendation.finding_id)
        if finding is None:
            raise GroundingRenderError("recommendation references an unknown code finding")
        if (
            recommendation.supporting_fact_ids != finding.supporting_fact_ids
            or recommendation.supporting_evidence_ids
            != finding.supporting_evidence_ids
        ):
            raise GroundingRenderError("recommendation support differs from its code finding")


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
