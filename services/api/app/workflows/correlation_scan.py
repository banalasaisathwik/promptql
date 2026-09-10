from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Annotated

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
from app.investigations import Evidence, EvidenceKind, InvestigationIdentifier
from app.investigations.fact_derivation import derive_code_failure_facts, derive_deployment_code_facts


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


async def _correlate_issue(
    issue_id: str,
    short_id: str,
    repository_owner: str,
    repository_name: str,
    sentry_source: HttpSentrySource,
    github_source: GitHubCodeEvidenceSource,
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
    )


async def scan_repository_for_correlations(
    *,
    repository_owner: str,
    repository_name: str,
    sentry_project_slug: str,
    sentry_source: HttpSentrySource,
    github_source: GitHubCodeEvidenceSource,
    max_issues: int = MAX_ISSUES_PER_SCAN,
) -> RepositoryCorrelationScanResult:
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
                repository_owner,
                repository_name,
                sentry_source,
                github_source,
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
