"""Deterministic developer recommendations from validated code findings."""

from hashlib import sha256

from app.investigations.code_diagnosis.models import (
    CodeFindingCategory,
    DeveloperRecommendation,
    DeveloperRecommendationCode,
    ValidatedCodeFinding,
)


_CATEGORY_RECOMMENDATION = {
    CodeFindingCategory.ERROR_HANDLING_OR_NULL_PATH: (
        DeveloperRecommendationCode.VALIDATE_ERROR_HANDLING,
        "Validate the null and error-handling path at the observed failure location.",
    ),
    CodeFindingCategory.INPUT_VALIDATION: (
        DeveloperRecommendationCode.VALIDATE_INPUT_BOUNDARY,
        "Validate inputs at the boundary that reaches the observed failure location.",
    ),
    CodeFindingCategory.STATE_OR_RESOURCE_LIFECYCLE: (
        DeveloperRecommendationCode.INSPECT_RESOURCE_LIFECYCLE,
        "Inspect resource and state lifecycle around the observed failure location.",
    ),
    CodeFindingCategory.CONFIGURATION_OR_DEPLOYMENT: (
        DeveloperRecommendationCode.COMPARE_DEPLOYMENT_CONFIGURATION,
        "Compare deployment configuration before and during the incident.",
    ),
}


def build_developer_recommendations(
    findings: tuple[ValidatedCodeFinding, ...],
) -> tuple[DeveloperRecommendation, ...]:
    # PURPOSE: Produce bounded, read-only next steps from accepted findings.
    #
    # FLOW: Add a universal inspection action -> optionally map the closed
    # finding category to one focused check -> add a regression-test action.
    # Candidate explanations and suggestions are intentionally absent.
    #
    # WATCH OUT: These are developer recommendations, never executable tools or
    # proof that the suspected category is the actual production root cause.
    recommendations: list[DeveloperRecommendation] = []
    for finding in findings:
        actions = [
            (
                DeveloperRecommendationCode.INSPECT_FAILURE_PATH,
                f"Inspect {finding.file_path}{_location_suffix(finding)} against the supporting Evidence.",
            ),
        ]
        category_action = _CATEGORY_RECOMMENDATION.get(finding.category)
        if category_action is not None:
            actions.append(category_action)
        actions.append(
            (
                DeveloperRecommendationCode.ADD_REGRESSION_TEST,
                "Add a regression test that reproduces the validated failure path before applying a fix.",
            )
        )
        for code, message in actions:
            recommendations.append(
                DeveloperRecommendation(
                    recommendation_id=_recommendation_id(finding.finding_id, code),
                    code=code,
                    message=message,
                    finding_id=finding.finding_id,
                    supporting_fact_ids=finding.supporting_fact_ids,
                    supporting_evidence_ids=finding.supporting_evidence_ids,
                )
            )
    return tuple(recommendations)


def _location_suffix(finding: ValidatedCodeFinding) -> str:
    if finding.function_name is not None and finding.line_number is not None:
        return f" in {finding.function_name} at line {finding.line_number}"
    if finding.function_name is not None:
        return f" in {finding.function_name}"
    if finding.line_number is not None:
        return f" at line {finding.line_number}"
    return ""


def _recommendation_id(
    finding_id: str,
    code: DeveloperRecommendationCode,
) -> str:
    digest = sha256(f"{finding_id}:{code.value}".encode()).hexdigest()[:16]
    return f"recommendation:{digest}"
