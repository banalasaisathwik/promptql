import logging
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field

from app.connectors.errors import (
    ConnectorErrorCategory,
    ConnectorUnavailableError,
    FixtureNotFoundError,
    GitHubConnectorError,
    JiraConnectorError,
    SentryConnectorError,
)
from app.connectors.models import (
    CommitSha,
    ContractModel,
    FailureLocationEvidenceRequest,
    GitHubCommitEvidenceRequest,
    JiraIssueKey,
    NonEmptyString,
    SentryOpenIssuesRequest,
)
from app.connectors.protocols import GitHubCodeEvidenceSource
from app.connectors.sentry_http import HttpSentrySource
from app.explanations import FakeLLMClient, TypedLLMClient
from app.investigations import (
    ChangedFileFact,
    ChangedFileMatchesFailureFileFact,
    ChangedHunkOverlapsFailureLineFact,
    Evidence,
    EvidenceKind,
    FactSet,
    InvestigationFact,
    InvestigationIdentifier,
    InvestigationRequest,
    StackFrameEvidenceContent,
)
from app.investigations.code_diagnosis import (
    CodeContextBuilder,
    CodeDiagnosisError,
    CodeFixProposalError,
    CodeFixStatus,
    DeterministicCodeFindingValidator,
    DeterministicCodeFixValidator,
    DeveloperRecommendation,
    FixProposalContextBuilder,
    ProposedCodeFix,
    TypedLLMCodeDiagnoser,
    TypedLLMFixProposalGenerator,
    ValidatedCodeFinding,
    build_developer_recommendations,
)
from app.investigations.fact_derivation import derive_code_failure_facts, derive_deployment_code_facts
from app.investigations.path_normalization import paths_match
from app.investigations.hypotheses import (
    DeterministicHypothesisValidator,
    GroundedCodeFinding,
    GroundedHypothesis,
    GroundedTerminationReason,
    HypothesisGenerationError,
    HypothesisGenerationInput,
    TypedLLMHypothesisGenerator,
    render_grounded_result,
)
from app.observability import NoOpRuntimeTelemetry, RuntimeTelemetry


MAX_ISSUES_PER_SCAN = 5


GITHUB_COMMIT_FILE_LIST_SUSPECTED_CAP = 300

_RETRYABLE_CATEGORIES = frozenset(
    {
        ConnectorErrorCategory.RATE_LIMITED,
        ConnectorErrorCategory.TIMEOUT,
        ConnectorErrorCategory.UPSTREAM_UNAVAILABLE,
    }
)

_ScanConnectorError = (
    SentryConnectorError,
    GitHubConnectorError,
    JiraConnectorError,
    ConnectorUnavailableError,
    FixtureNotFoundError,
)


class ScanStep(StrEnum):
    FAILURE_LOCATION = "failure_location"
    LINKED_JIRA_KEY = "linked_jira_key"
    ISSUE_COMMIT_SHA = "issue_commit_sha"
    COMMIT_EVIDENCE = "commit_evidence"
    COMMIT_CHANGED_FILE_EVIDENCE = "commit_changed_file_evidence"


class IssueCorrelationStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"


class StepFailure(ContractModel):
    step: ScanStep
    failure_code: ConnectorErrorCategory


class IssueAnalysisStatus(StrEnum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    HYPOTHESIS_GENERATION_FAILED = "hypothesis_generation_failed"
    NO_VALIDATED_HYPOTHESIS = "no_validated_hypothesis"
    CODE_FINDING_UNAVAILABLE = "code_finding_unavailable"
    COMPLETED = "completed"


    ANALYSIS_ERROR = "analysis_error"


class GroundingStrength(StrEnum):
    STRONG = "strong"
    MODERATE = "moderate"
    INSUFFICIENT = "insufficient"


class IssueGroundedAnalysis(ContractModel):
    status: IssueAnalysisStatus
    hypotheses: tuple[GroundedHypothesis, ...] = ()
    code_findings: tuple[GroundedCodeFinding, ...] = ()
    recommendations: tuple[DeveloperRecommendation, ...] = ()
    proposed_fixes: tuple[ProposedCodeFix, ...] = ()
    fix_status: CodeFixStatus = CodeFixStatus.UNAVAILABLE


class FactSummary(ContractModel):
    fact_id: InvestigationIdentifier
    fact_type: str
    label: str
    detail: str | None = None


class CorrelationScanPresentation(ContractModel):
    issue_title: str | None = None
    failure_file_path: str | None = None
    failure_line_number: int | None = None
    failure_function_name: str | None = None
    fact_summaries: tuple[FactSummary, ...] = ()


    grounding_strength: GroundingStrength = GroundingStrength.INSUFFICIENT


class IssueCorrelationResult(ContractModel):
    sentry_issue_id: NonEmptyString
    sentry_short_id: NonEmptyString
    jira_ticket: JiraIssueKey | None
    commit_sha: CommitSha | None


    pull_request_number: Annotated[int, Field(strict=True, gt=0)] | None
    evidence_ids: tuple[InvestigationIdentifier, ...]
    fact_ids: tuple[InvestigationIdentifier, ...]
    possibly_truncated_file_list: bool
    status: IssueCorrelationStatus
    step_failures: tuple[StepFailure, ...]
    presentation: CorrelationScanPresentation
    analysis: IssueGroundedAnalysis


class RepositoryCorrelationScanResult(ContractModel):
    repository_owner: NonEmptyString
    repository_name: NonEmptyString
    total_open_issues_found: int
    issues_scanned: int
    truncated: bool
    results: tuple[IssueCorrelationResult, ...]


def _failure_category(error: Exception) -> ConnectorErrorCategory:
    if isinstance(error, (SentryConnectorError, GitHubConnectorError, JiraConnectorError)):
        return error.category
    if isinstance(error, ConnectorUnavailableError):
        return ConnectorErrorCategory.CONFIGURATION_ERROR
    if isinstance(error, FixtureNotFoundError):
        return ConnectorErrorCategory.NOT_FOUND
    raise error


def render_correlation_fact_summary(
    fact: InvestigationFact, commit_sha: CommitSha | None
) -> FactSummary | None:
    if isinstance(fact, ChangedFileFact):
        commit_prefix = (
            f"Commit {commit_sha[:7]}" if commit_sha is not None else "Changed file"
        )
        return FactSummary(
            fact_id=fact.fact_id,
            fact_type=fact.fact_type,
            label="Changed file",
            detail=f"{commit_prefix} changed {fact.path}",
        )
    if isinstance(fact, ChangedFileMatchesFailureFileFact):
        return FactSummary(
            fact_id=fact.fact_id,
            fact_type=fact.fact_type,
            label="Failure-file match",
            detail="The changed file matches the recorded Sentry failure path",
        )
    if isinstance(fact, ChangedHunkOverlapsFailureLineFact):
        return FactSummary(
            fact_id=fact.fact_id,
            fact_type=fact.fact_type,
            label="Diff overlap",
            detail=f"The changed diff hunk overlaps failure line {fact.line_number}",
        )
    return None


def _build_presentation(
    *,
    issue_title: str | None,
    failure_location: Evidence | None,
    facts: FactSet,
    commit_sha: CommitSha | None,
) -> CorrelationScanPresentation:
    content = failure_location.content if failure_location is not None else None
    stack_frame = content if isinstance(content, StackFrameEvidenceContent) else None
    summaries = tuple(
        summary
        for fact in facts
        if (summary := render_correlation_fact_summary(fact, commit_sha)) is not None
    )
    return CorrelationScanPresentation(
        issue_title=issue_title,
        failure_file_path=stack_frame.file_path if stack_frame is not None else None,
        failure_line_number=stack_frame.line_number if stack_frame is not None else None,
        failure_function_name=stack_frame.function_name if stack_frame is not None else None,
        fact_summaries=summaries,
        grounding_strength=_grounding_strength(facts),
    )


def _grounding_strength(facts: FactSet) -> GroundingStrength:
    matched_failure_paths = tuple(
        fact.file_path
        for fact in facts
        if isinstance(fact, ChangedFileMatchesFailureFileFact)
    )
    if any(
        isinstance(fact, ChangedHunkOverlapsFailureLineFact)
        and any(paths_match(fact.file_path, path) for path in matched_failure_paths)
        for fact in facts
    ):
        return GroundingStrength.STRONG
    if matched_failure_paths:
        return GroundingStrength.MODERATE
    return GroundingStrength.INSUFFICIENT


async def _call_step[T](
    step: ScanStep,
    call: Callable[[], Awaitable[T]],
) -> tuple[T | None, StepFailure | None]:
    try:
        return await call(), None
    except _ScanConnectorError as error:
        category = _failure_category(error)
        if category not in _RETRYABLE_CATEGORIES:
            return None, StepFailure(step=step, failure_code=category)
    try:
        return await call(), None
    except _ScanConnectorError as error:
        return None, StepFailure(step=step, failure_code=_failure_category(error))


def _issue_investigation_goal(short_id: str) -> str:
    return (
        f"Determine whether the observed code changes associated with "
        f"Sentry issue {short_id} plausibly explain its recorded failure "
        f"location."
    )


def _has_hypothesis_worthy_facts(facts: FactSet) -> bool:
    return any(
        isinstance(fact, (ChangedFileMatchesFailureFileFact, ChangedHunkOverlapsFailureLineFact))
        for fact in facts
    )


def _provider_failure_fields(
    error: HypothesisGenerationError | CodeDiagnosisError | CodeFixProposalError,
) -> dict[str, object]:
    details = error.provider_details
    return {
        "exception_class": type(error).__name__,
        "failure_code": error.code.value,
        "failure_category": error.provider_failure_category,
        "http_status": details.http_status if details is not None else None,
        "provider_type": details.provider_type if details is not None else None,
        "provider_code": details.provider_code if details is not None else None,
        "provider_message": (
            details.provider_message if details is not None else str(error)
        ),
        "failed_generation_present": (
            details.failed_generation_present if details is not None else False
        ),
        "failed_generation_length": (
            details.failed_generation_length if details is not None else None
        ),
    }


async def _generate_issue_analysis(
    *,
    log_id: UUID,
    issue_id: str,
    short_id: str,
    repository_owner: str,
    repository_name: str,
    facts: FactSet,
    evidence: tuple[Evidence, ...],
    hypothesis_client: TypedLLMClient,
    code_diagnosis_client: TypedLLMClient,
    fix_proposal_client: TypedLLMClient,
    telemetry: RuntimeTelemetry,
) -> IssueGroundedAnalysis:
    sorted_facts = tuple(sorted(facts, key=lambda fact: fact.fact_id))
    generation_input = HypothesisGenerationInput(
        investigation_goal=_issue_investigation_goal(short_id),
        facts=sorted_facts,
    )
    telemetry.event_logger.emit(
        "correlation.hypothesis.started",
        run_id=log_id,
        sentry_issue_id=issue_id,
        facts_count=len(facts),
    )
    try:
        generated_hypotheses = await TypedLLMHypothesisGenerator(
            hypothesis_client
        ).generate(generation_input)
    except HypothesisGenerationError as error:
        telemetry.record_investigation_diagnostic_failure(
            log_id,
            "correlation.hypothesis.failed",
            sentry_issue_id=issue_id,
            llm_provider=hypothesis_client.provider.value,
            requested_model=hypothesis_client.model,
            **_provider_failure_fields(error),
        )
        return IssueGroundedAnalysis(status=IssueAnalysisStatus.HYPOTHESIS_GENERATION_FAILED)

    telemetry.record_llm_token_usage(
        log_id, "hypothesis", generated_hypotheses.metadata.token_usage
    )
    telemetry.event_logger.emit(
        "correlation.hypothesis.completed",
        run_id=log_id,
        sentry_issue_id=issue_id,
        llm_provider=generated_hypotheses.metadata.provider,
        requested_model=generated_hypotheses.metadata.requested_model,
        prompt_version=generated_hypotheses.metadata.prompt_version,
        hypothesis_count=len(generated_hypotheses.candidates),
    )

    hypothesis_validation = DeterministicHypothesisValidator().validate(
        generated_hypotheses.candidates, facts
    )
    for rejected in hypothesis_validation.rejected_candidates:
        telemetry.record_hypothesis_validation_rejected(
            log_id,
            rejected.candidate.subject,
            rejected.candidate.kind.value,
            rejected.candidate.supporting_fact_ids,
            rejected.reason.value,
        )
    validated_hypotheses = hypothesis_validation.accepted_hypotheses
    if not validated_hypotheses:
        return IssueGroundedAnalysis(status=IssueAnalysisStatus.NO_VALIDATED_HYPOTHESIS)


    request = InvestigationRequest(
        repository_owner=repository_owner,
        repository_name=repository_name,
        question=_issue_investigation_goal(short_id),
        incident_reference=issue_id,
    )
    diagnosis_input = CodeContextBuilder().build(
        request, validated_hypotheses, facts, evidence
    )
    telemetry.event_logger.emit(
        "correlation.code_diagnosis.started",
        run_id=log_id,
        sentry_issue_id=issue_id,
        location_count=len(diagnosis_input.locations),
    )
    validated_findings: tuple[ValidatedCodeFinding, ...] = ()
    try:
        generated_findings = await TypedLLMCodeDiagnoser(code_diagnosis_client).generate(
            diagnosis_input
        )
    except CodeDiagnosisError as error:
        telemetry.record_investigation_diagnostic_failure(
            log_id,
            "correlation.code_diagnosis.failed",
            sentry_issue_id=issue_id,
            llm_provider=code_diagnosis_client.provider.value,
            requested_model=code_diagnosis_client.model,
            **_provider_failure_fields(error),
        )
    else:
        telemetry.record_llm_token_usage(
            log_id, "code_diagnosis", generated_findings.metadata.token_usage
        )
        telemetry.event_logger.emit(
            "correlation.code_diagnosis.completed",
            run_id=log_id,
            sentry_issue_id=issue_id,
            llm_provider=generated_findings.metadata.provider,
            requested_model=generated_findings.metadata.requested_model,
            prompt_version=generated_findings.metadata.prompt_version,
        )
        finding_validation = DeterministicCodeFindingValidator().validate(
            generated_findings.candidates, validated_hypotheses, facts, evidence
        )
        for rejected in finding_validation.rejected_candidates:
            telemetry.event_logger.emit(
                "correlation.code_diagnosis.validation_rejected",
                logging.WARNING,
                run_id=log_id,
                sentry_issue_id=issue_id,
                failure_code=rejected.reason.value,
            )
        validated_findings = finding_validation.accepted_findings

    proposed_fixes: list[ProposedCodeFix] = []
    hypotheses_by_id = {item.hypothesis_id: item for item in diagnosis_input.hypotheses}
    for finding in validated_findings:
        hypothesis = hypotheses_by_id.get(finding.hypothesis_id)
        proposal_input = (
            FixProposalContextBuilder().build(finding, hypothesis, facts, evidence)
            if hypothesis is not None
            else None
        )
        if proposal_input is None:
            telemetry.event_logger.emit(
                "correlation.code_fix.unavailable",
                run_id=log_id,
                sentry_issue_id=issue_id,
                reason="source_context_unavailable",
            )
            continue
        telemetry.event_logger.emit(
            "correlation.code_fix.started",
            run_id=log_id,
            sentry_issue_id=issue_id,
            source_line_count=len(proposal_input.original_hunk.splitlines()),
        )
        try:
            candidate = await TypedLLMFixProposalGenerator(fix_proposal_client).generate(
                proposal_input
            )
        except CodeFixProposalError as error:
            telemetry.record_investigation_diagnostic_failure(
                log_id,
                "correlation.code_fix.failed",
                sentry_issue_id=issue_id,
                llm_provider=fix_proposal_client.provider.value,
                requested_model=fix_proposal_client.model,
                **_provider_failure_fields(error),
            )
            continue
        if candidate is None:
            telemetry.event_logger.emit(
                "correlation.code_fix.unavailable",
                run_id=log_id,
                sentry_issue_id=issue_id,
                reason="no_safe_proposal",
            )
            continue
        validation = DeterministicCodeFixValidator().validate(candidate, proposal_input)
        for rejected in validation.rejected_candidates:
            telemetry.event_logger.emit(
                "correlation.code_fix.rejected",
                logging.WARNING,
                run_id=log_id,
                sentry_issue_id=issue_id,
                failure_code=rejected.reason.value,
            )
        if validation.accepted_fixes:
            proposed_fixes.extend(validation.accepted_fixes)
            telemetry.event_logger.emit(
                "correlation.code_fix.completed",
                run_id=log_id,
                sentry_issue_id=issue_id,
            )

    recommendations = build_developer_recommendations(validated_findings)


    rendered = render_grounded_result(
        facts,
        validated_hypotheses,
        (),
        GroundedTerminationReason.COMPLETED,
        validated_findings,
        recommendations,
        tuple(item.evidence_id for item in evidence),
    )
    status = (
        IssueAnalysisStatus.COMPLETED
        if validated_findings
        else IssueAnalysisStatus.CODE_FINDING_UNAVAILABLE
    )
    return IssueGroundedAnalysis(
        status=status,
        hypotheses=rendered.supported_hypotheses,
        code_findings=rendered.code_findings,
        recommendations=rendered.recommendations,
        proposed_fixes=tuple(proposed_fixes),
        fix_status=(
            CodeFixStatus.AVAILABLE if proposed_fixes else CodeFixStatus.UNAVAILABLE
        ),
    )


async def _run_issue_analysis(
    *,
    issue_id: str,
    short_id: str,
    repository_owner: str,
    repository_name: str,
    facts: FactSet,
    evidence: tuple[Evidence, ...],
    hypothesis_client: TypedLLMClient,
    code_diagnosis_client: TypedLLMClient,
    fix_proposal_client: TypedLLMClient,
    telemetry: RuntimeTelemetry,
) -> IssueGroundedAnalysis:
    if not _has_hypothesis_worthy_facts(facts):
        return IssueGroundedAnalysis(status=IssueAnalysisStatus.INSUFFICIENT_EVIDENCE)

    log_id = uuid4()
    try:
        return await _generate_issue_analysis(
            log_id=log_id,
            issue_id=issue_id,
            short_id=short_id,
            repository_owner=repository_owner,
            repository_name=repository_name,
            facts=facts,
            evidence=evidence,
            hypothesis_client=hypothesis_client,
            code_diagnosis_client=code_diagnosis_client,
            fix_proposal_client=fix_proposal_client,
            telemetry=telemetry,
        )
    except Exception as error:
        telemetry.record_investigation_diagnostic_failure(
            log_id,
            "correlation.analysis.unexpected_error",
            sentry_issue_id=issue_id,
            exception_class=type(error).__name__,
        )
        return IssueGroundedAnalysis(status=IssueAnalysisStatus.ANALYSIS_ERROR)


async def _correlate_issue(
    issue_id: str,
    short_id: str,
    issue_title: str | None,
    repository_owner: str,
    repository_name: str,
    sentry_source: HttpSentrySource,
    github_source: GitHubCodeEvidenceSource,
    hypothesis_client: TypedLLMClient,
    code_diagnosis_client: TypedLLMClient,
    fix_proposal_client: TypedLLMClient,
    telemetry: RuntimeTelemetry,
) -> IssueCorrelationResult:
    step_failures: list[StepFailure] = []
    evidence: list[Evidence] = []

    failure_location, failure = await _call_step(
        ScanStep.FAILURE_LOCATION,
        lambda: sentry_source.get_failure_location_evidence(
            FailureLocationEvidenceRequest(incident_reference=issue_id)
        ),
    )
    if failure_location is not None:
        evidence.append(failure_location)
    if failure is not None:
        step_failures.append(failure)


    jira_ticket, failure = await _call_step(
        ScanStep.LINKED_JIRA_KEY,
        lambda: sentry_source.get_linked_jira_key(issue_id),
    )
    if failure is not None:
        step_failures.append(failure)

    commit_sha, failure = await _call_step(
        ScanStep.ISSUE_COMMIT_SHA,
        lambda: sentry_source.get_issue_commit_sha(issue_id),
    )
    if failure is not None:
        step_failures.append(failure)

    possibly_truncated_file_list = False
    if commit_sha is not None:
        commit_request = GitHubCommitEvidenceRequest(
            repository_owner=repository_owner,
            repository_name=repository_name,
            commit_sha=commit_sha,
        )
        commit_evidence, failure = await _call_step(
            ScanStep.COMMIT_EVIDENCE,
            lambda: github_source.get_commit_evidence(commit_request),
        )
        if commit_evidence is not None:
            evidence.append(commit_evidence)
        if failure is not None:
            step_failures.append(failure)

        changed_file_evidence, failure = await _call_step(
            ScanStep.COMMIT_CHANGED_FILE_EVIDENCE,
            lambda: github_source.get_commit_changed_file_evidence(commit_request),
        )
        if changed_file_evidence is not None:
            evidence.extend(changed_file_evidence)
            changed_file_count = sum(
                1
                for item in changed_file_evidence
                if item.kind is EvidenceKind.COMMIT_CHANGED_FILE
            )
            possibly_truncated_file_list = (
                changed_file_count == GITHUB_COMMIT_FILE_LIST_SUSPECTED_CAP
            )
        if failure is not None:
            step_failures.append(failure)

    evidence_tuple = tuple(evidence)
    facts = (
        *derive_deployment_code_facts(evidence_tuple),
        *derive_code_failure_facts(evidence_tuple),
    )

    if not step_failures:
        status = IssueCorrelationStatus.OK
    elif evidence_tuple:
        status = IssueCorrelationStatus.PARTIAL
    else:
        status = IssueCorrelationStatus.FAILED


    analysis = await _run_issue_analysis(
        issue_id=issue_id,
        short_id=short_id,
        repository_owner=repository_owner,
        repository_name=repository_name,
        facts=facts,
        evidence=evidence_tuple,
        hypothesis_client=hypothesis_client,
        code_diagnosis_client=code_diagnosis_client,
        fix_proposal_client=fix_proposal_client,
        telemetry=telemetry,
    )
    presentation = _build_presentation(
        issue_title=issue_title,
        failure_location=failure_location,
        facts=facts,
        commit_sha=commit_sha,
    )

    return IssueCorrelationResult(
        sentry_issue_id=issue_id,
        sentry_short_id=short_id,
        jira_ticket=jira_ticket,
        commit_sha=commit_sha,
        pull_request_number=None,
        evidence_ids=tuple(item.evidence_id for item in evidence_tuple),
        fact_ids=tuple(fact.fact_id for fact in facts),
        possibly_truncated_file_list=possibly_truncated_file_list,
        status=status,
        step_failures=tuple(step_failures),
        presentation=presentation,
        analysis=analysis,
    )


async def scan_repository_for_correlations(
    *,
    repository_owner: str,
    repository_name: str,
    sentry_project_slug: str,
    sentry_source: HttpSentrySource,
    github_source: GitHubCodeEvidenceSource,
    max_issues: int = MAX_ISSUES_PER_SCAN,
    hypothesis_client: TypedLLMClient | None = None,
    code_diagnosis_client: TypedLLMClient | None = None,
    fix_proposal_client: TypedLLMClient | None = None,
    telemetry: RuntimeTelemetry | None = None,
) -> RepositoryCorrelationScanResult:
    resolved_hypothesis_client = hypothesis_client or FakeLLMClient()
    resolved_code_diagnosis_client = code_diagnosis_client or FakeLLMClient()
    resolved_fix_proposal_client = fix_proposal_client or FakeLLMClient()
    resolved_telemetry = telemetry or NoOpRuntimeTelemetry()

    open_issues = await sentry_source.list_open_issues(
        SentryOpenIssuesRequest(project_slug=sentry_project_slug)
    )
    scanned_issues = open_issues[:max_issues]

    results: list[IssueCorrelationResult] = []
    for issue in scanned_issues:
        results.append(
            await _correlate_issue(
                issue.issue_id,
                issue.short_id,
                issue.title,
                repository_owner,
                repository_name,
                sentry_source,
                github_source,
                resolved_hypothesis_client,
                resolved_code_diagnosis_client,
                resolved_fix_proposal_client,
                resolved_telemetry,
            )
        )

    return RepositoryCorrelationScanResult(
        repository_owner=repository_owner,
        repository_name=repository_name,
        total_open_issues_found=len(open_issues),
        issues_scanned=len(scanned_issues),
        truncated=len(open_issues) > len(scanned_issues),
        results=tuple(results),
    )
