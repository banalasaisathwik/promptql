from datetime import UTC, datetime
import unittest

import httpx

from app.connectors.github_code_fakes import (
    COMMIT_EVIDENCE_FIXTURES,
    FIXTURE_COMMIT_REQUEST,
    FakeGitHubCodeEvidenceSource,
)
from app.connectors.models import CommitSha, GitHubCommitEvidenceRequest
from app.connectors.sentry_http import HttpSentrySource
from app.explanations import FakeLLMClient
from app.explanations.errors import LLMProviderError, LLMProviderFailureCategory
from app.explanations.models import LLMProviderName, LLMStructuredResponse
from app.investigations import (
    ChangedFileMatchesFailureFileFact,
    ChangedHunkOverlapsFailureLineFact,
    CommitChangedFileEvidenceContent,
    CommitDiffHunkEvidenceContent,
    DiffLine,
    DiffLineKind,
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
    EvidenceSource,
    FileChangeType,
)
from app.investigations.hypotheses import (
    CandidateHypothesis,
    HypothesisGenerationOutput,
    HypothesisKind,
)
from app.workflows.correlation_scan import (
    GroundingStrength,
    IssueAnalysisStatus,
    IssueCorrelationStatus,
    RepositoryCorrelationScanResult,
    ScanStep,
    _grounding_strength,
    scan_repository_for_correlations,
)


ORGANIZATION_SLUG = "acme"
BASE_URL = "https://sentry.io/api/0"
REPO_OWNER = "octo-org"
REPO_NAME = "analytics"
COMMIT_SHA: CommitSha = "a" * 40
FIXTURE_TIME = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def issue_list_item(**updates) -> dict:
    payload = {
        "id": "1001",
        "shortId": "CHECKOUT-1001",
        "title": "KeyError: 0",
        "status": "unresolved",
        "firstSeen": "2026-08-17T11:40:00Z",
        "lastSeen": "2026-08-17T11:50:00Z",
        "project": {"id": "9", "slug": "checkout-api"},
    }
    payload.update(updates)
    return payload


def issue_detail(**updates) -> dict:
    payload = {
        "id": "1001",
        "shortId": "CHECKOUT-1001",
        "status": "unresolved",
        "firstSeen": "2026-08-17T11:40:00Z",
        "lastSeen": "2026-08-17T11:50:00Z",
        "project": {"id": "9", "slug": "checkout-api"},
        "firstRelease": {"version": COMMIT_SHA, "lastCommit": None},
    }
    payload.update(updates)
    return payload


def event_detail() -> dict:
    return {
        "eventID": "abc123",
        "entries": [
            {
                "type": "exception",
                "data": {
                    "values": [
                        {
                            "type": "ValueError",
                            "stacktrace": {
                                "frames": [
                                    {
                                        "filename": "services/checkout.py",
                                        "function": "create_order",
                                        "lineNo": 87,
                                    }
                                ]
                            },
                        }
                    ]
                },
            }
        ],
    }


def integrations_payload(*, jira_key: str | None) -> list:
    external_issues = [] if jira_key is None else [{"id": "1", "key": jira_key}]
    return [
        {
            "id": "1",
            "provider": {"key": "jira", "slug": "jira", "name": "Jira"},
            "externalIssues": external_issues,
        }
    ]


class ScanSentryRouter:
    def __init__(self, *, issue_count: int = 1, jira_key: str | None = "KAN-5") -> None:
        self.issues = [
            issue_list_item(id=str(1001 + index), shortId=f"CHECKOUT-{1001 + index}")
            for index in range(issue_count)
        ]
        self.jira_key = jira_key
        self.detail_overrides: dict[str, dict] = {}


        self.integrations_first_status: dict[str, int] = {}
        self._integrations_attempts: dict[str, int] = {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path

        if path.endswith("/issues/") and "/projects/" in path:
            return httpx.Response(200, json=self.issues)
        if path.endswith("/events/latest/"):
            return httpx.Response(200, json=event_detail())
        if path.endswith("/integrations/"):
            issue_id = path.split("/issues/")[1].split("/")[0]
            first_failure_status = self.integrations_first_status.get(issue_id)
            attempt = self._integrations_attempts.get(issue_id, 0) + 1
            self._integrations_attempts[issue_id] = attempt
            if first_failure_status is not None and attempt == 1:
                return httpx.Response(first_failure_status)
            return httpx.Response(200, json=integrations_payload(jira_key=self.jira_key))
        if "/issues/" in path:
            issue_id = path.rstrip("/").split("/")[-1]
            override = self.detail_overrides.get(issue_id)
            if override is not None:
                return override
            return httpx.Response(
                200, json=issue_detail(id=issue_id, shortId=f"CHECKOUT-{issue_id}")
            )
        raise AssertionError(f"unexpected Sentry path {path}")


def create_sentry_source(router: ScanSentryRouter) -> HttpSentrySource:
    client = httpx.AsyncClient(
        base_url=BASE_URL,
        headers={"Authorization": "Bearer test-sentry-token"},
        transport=httpx.MockTransport(router),
    )
    return HttpSentrySource(client, ORGANIZATION_SLUG)


class RecordingGitHubSource:
    def __init__(self, inner: FakeGitHubCodeEvidenceSource) -> None:
        self._inner = inner
        self.source = inner.source
        self.calls: list[str] = []

    async def get_commit_evidence(self, request):
        self.calls.append("get_commit_evidence")
        return await self._inner.get_commit_evidence(request)

    async def get_pull_request_evidence(self, request):
        self.calls.append("get_pull_request_evidence")
        return await self._inner.get_pull_request_evidence(request)

    async def get_changed_file_evidence(self, request):
        self.calls.append("get_changed_file_evidence")
        return await self._inner.get_changed_file_evidence(request)

    async def get_commit_changed_file_evidence(self, request):
        self.calls.append("get_commit_changed_file_evidence")
        return await self._inner.get_commit_changed_file_evidence(request)


def _commit_changed_file_evidence(file_count: int) -> tuple[Evidence, ...]:
    return tuple(
        Evidence(
            evidence_id=f"github:scan:commit:file:{index}",
            source=EvidenceSource.GITHUB,
            kind=EvidenceKind.COMMIT_CHANGED_FILE,
            provenance=EvidenceProvenance(
                source_reference=f"github:scan:commit:file:{index}",
                retrieved_at=FIXTURE_TIME,
            ),
            content=CommitChangedFileEvidenceContent(
                repository_owner=REPO_OWNER,
                repository_name=REPO_NAME,
                commit_sha=COMMIT_SHA,
                path=f"services/checkout_{index}.py",
                change_type=FileChangeType.MODIFIED,
                additions=1,
                deletions=1,
                changes=2,
                patch_available=False,
            ),
        )
        for index in range(file_count)
    )


def github_source_with_commit(*, file_count: int = 1) -> FakeGitHubCodeEvidenceSource:
    request = GitHubCommitEvidenceRequest(
        repository_owner=REPO_OWNER, repository_name=REPO_NAME, commit_sha=COMMIT_SHA
    )
    fixture_commit = COMMIT_EVIDENCE_FIXTURES[FIXTURE_COMMIT_REQUEST]
    commit = fixture_commit.model_copy(
        update={
            "evidence_id": "github:scan:commit",
            "content": fixture_commit.content.model_copy(
                update={
                    "repository_owner": REPO_OWNER,
                    "repository_name": REPO_NAME,
                    "commit_sha": COMMIT_SHA,
                }
            ),
        }
    )
    return FakeGitHubCodeEvidenceSource(
        commit_fixtures={request: commit},
        commit_changed_file_fixtures={request: _commit_changed_file_evidence(file_count)},
    )


def _issue_detail_paths(router: ScanSentryRouter) -> set[str]:
    return {
        request.url.path.rstrip("/").split("/")[-1]
        for request in router.requests
        if "/issues/" in request.url.path
        and "/projects/" not in request.url.path
        and not request.url.path.endswith("/events/latest/")
        and "/integrations/" not in request.url.path
    }


class CorrelationScanTests(unittest.IsolatedAsyncioTestCase):
    def test_grounding_strength_does_not_combine_different_failure_paths(self) -> None:
        facts = (
            ChangedFileMatchesFailureFileFact(
                fact_id="F_MATCH", evidence_reference_ids=("E_MATCH",), file_path="app/a.py"
            ),
            ChangedHunkOverlapsFailureLineFact(
                fact_id="F_HUNK", evidence_reference_ids=("E_HUNK",), file_path="app/b.py", line_number=9
            ),
        )

        self.assertIs(_grounding_strength(facts), GroundingStrength.MODERATE)

    async def test_presentation_projects_bounded_issue_metadata_and_facts(self) -> None:
        router = ScanSentryRouter(issue_count=1, jira_key="KAN-5")
        sentry_source = create_sentry_source(router)
        github_source = github_source_with_matching_commit()
        try:
            result = await scan_repository_for_correlations(
                repository_owner=REPO_OWNER,
                repository_name=REPO_NAME,
                sentry_project_slug="checkout-api",
                sentry_source=sentry_source,
                github_source=github_source,
            )
        finally:
            await sentry_source.aclose()

        presentation = result.results[0].presentation
        self.assertEqual(presentation.issue_title, "KeyError: 0")
        self.assertEqual(presentation.failure_file_path, "services/checkout.py")
        self.assertEqual(presentation.failure_line_number, 87)
        self.assertEqual(presentation.failure_function_name, "create_order")
        self.assertIs(presentation.grounding_strength, GroundingStrength.STRONG)
        summaries = {summary.fact_type: summary for summary in presentation.fact_summaries}
        self.assertEqual(summaries["changed_file"].label, "Changed file")
        self.assertEqual(
            summaries["changed_file"].detail,
            "Commit aaaaaaa changed services/checkout.py",
        )
        self.assertEqual(
            summaries["changed_file_matches_failure_file"].label,
            "Failure-file match",
        )
        self.assertEqual(
            summaries["changed_hunk_overlaps_failure_line"].detail,
            "The changed diff hunk overlaps failure line 87",
        )

    async def test_ok_status_with_linked_jira_ticket_and_resolved_commit(self) -> None:
        router = ScanSentryRouter(issue_count=1, jira_key="KAN-5")
        sentry_source = create_sentry_source(router)
        github_source = github_source_with_commit(file_count=2)
        try:
            result = await scan_repository_for_correlations(
                repository_owner=REPO_OWNER,
                repository_name=REPO_NAME,
                sentry_project_slug="checkout-api",
                sentry_source=sentry_source,
                github_source=github_source,
            )
        finally:
            await sentry_source.aclose()

        self.assertIsInstance(result, RepositoryCorrelationScanResult)
        self.assertEqual(result.total_open_issues_found, 1)
        self.assertEqual(result.issues_scanned, 1)
        self.assertFalse(result.truncated)
        issue_result = result.results[0]
        self.assertEqual(issue_result.status, IssueCorrelationStatus.OK)
        self.assertEqual(issue_result.jira_ticket, "KAN-5")
        self.assertEqual(issue_result.commit_sha, COMMIT_SHA)
        self.assertIsNone(issue_result.pull_request_number)
        self.assertEqual(issue_result.step_failures, ())
        self.assertFalse(issue_result.possibly_truncated_file_list)
        self.assertTrue(issue_result.evidence_ids)
        self.assertTrue(issue_result.fact_ids)

    async def test_unlinked_issue_has_no_jira_ticket_and_no_step_failure_for_it(self) -> None:
        router = ScanSentryRouter(issue_count=1, jira_key=None)
        sentry_source = create_sentry_source(router)
        github_source = github_source_with_commit()
        try:
            result = await scan_repository_for_correlations(
                repository_owner=REPO_OWNER,
                repository_name=REPO_NAME,
                sentry_project_slug="checkout-api",
                sentry_source=sentry_source,
                github_source=github_source,
            )
        finally:
            await sentry_source.aclose()

        issue_result = result.results[0]
        self.assertIsNone(issue_result.jira_ticket)
        self.assertEqual(issue_result.status, IssueCorrelationStatus.OK)
        self.assertNotIn(
            ScanStep.LINKED_JIRA_KEY, [failure.step for failure in issue_result.step_failures]
        )

    async def test_github_not_found_yields_partial_status_not_a_crash(self) -> None:
        router = ScanSentryRouter(issue_count=1, jira_key="KAN-5")
        sentry_source = create_sentry_source(router)

        github_source = FakeGitHubCodeEvidenceSource(
            commit_fixtures={}, commit_changed_file_fixtures={}
        )
        try:
            result = await scan_repository_for_correlations(
                repository_owner=REPO_OWNER,
                repository_name=REPO_NAME,
                sentry_project_slug="checkout-api",
                sentry_source=sentry_source,
                github_source=github_source,
            )
        finally:
            await sentry_source.aclose()

        issue_result = result.results[0]
        self.assertEqual(issue_result.status, IssueCorrelationStatus.PARTIAL)
        self.assertTrue(issue_result.evidence_ids)
        self.assertEqual(issue_result.presentation.issue_title, "KeyError: 0")
        self.assertEqual(
            issue_result.presentation.failure_file_path, "services/checkout.py"
        )
        self.assertEqual(issue_result.presentation.failure_line_number, 87)
        failed_steps = {failure.step for failure in issue_result.step_failures}
        self.assertIn(ScanStep.COMMIT_EVIDENCE, failed_steps)
        self.assertIn(ScanStep.COMMIT_CHANGED_FILE_EVIDENCE, failed_steps)

    async def test_no_resolvable_commit_skips_github_entirely(self) -> None:
        router = ScanSentryRouter(issue_count=1, jira_key="KAN-5")
        router.detail_overrides["1001"] = httpx.Response(
            200,
            json=issue_detail(
                id="1001",
                shortId="CHECKOUT-1001",
                firstRelease={"version": "checkout@1.0.0", "lastCommit": None},
            ),
        )
        sentry_source = create_sentry_source(router)
        github_source = RecordingGitHubSource(github_source_with_commit())
        try:
            result = await scan_repository_for_correlations(
                repository_owner=REPO_OWNER,
                repository_name=REPO_NAME,
                sentry_project_slug="checkout-api",
                sentry_source=sentry_source,
                github_source=github_source,
            )
        finally:
            await sentry_source.aclose()

        issue_result = result.results[0]
        self.assertIsNone(issue_result.commit_sha)
        self.assertEqual(issue_result.status, IssueCorrelationStatus.OK)
        self.assertEqual(issue_result.step_failures, ())
        self.assertEqual(github_source.calls, [])

    async def test_cap_truncates_before_fan_out_and_reports_it_non_silently(self) -> None:
        router = ScanSentryRouter(issue_count=8, jira_key="KAN-5")
        sentry_source = create_sentry_source(router)
        github_source = github_source_with_commit()
        try:
            result = await scan_repository_for_correlations(
                repository_owner=REPO_OWNER,
                repository_name=REPO_NAME,
                sentry_project_slug="checkout-api",
                sentry_source=sentry_source,
                github_source=github_source,
                max_issues=3,
            )
        finally:
            await sentry_source.aclose()

        self.assertEqual(result.total_open_issues_found, 8)
        self.assertEqual(result.issues_scanned, 3)
        self.assertTrue(result.truncated)
        self.assertEqual(len(result.results), 3)

        self.assertEqual(_issue_detail_paths(router), {"1001", "1002", "1003"})

    async def test_possibly_truncated_file_list_flag_set_at_the_suspected_cap(self) -> None:
        router = ScanSentryRouter(issue_count=1, jira_key="KAN-5")
        sentry_source = create_sentry_source(router)
        github_source = github_source_with_commit(file_count=300)
        try:
            result = await scan_repository_for_correlations(
                repository_owner=REPO_OWNER,
                repository_name=REPO_NAME,
                sentry_project_slug="checkout-api",
                sentry_source=sentry_source,
                github_source=github_source,
            )
        finally:
            await sentry_source.aclose()

        self.assertTrue(result.results[0].possibly_truncated_file_list)

    async def test_jira_lookup_failure_is_distinguishable_from_confirmed_unlinked(self) -> None:
        router = ScanSentryRouter(issue_count=1, jira_key="KAN-5")


        router.integrations_first_status["1001"] = 401
        sentry_source = create_sentry_source(router)
        github_source = github_source_with_commit()
        try:
            result = await scan_repository_for_correlations(
                repository_owner=REPO_OWNER,
                repository_name=REPO_NAME,
                sentry_project_slug="checkout-api",
                sentry_source=sentry_source,
                github_source=github_source,
            )
        finally:
            await sentry_source.aclose()

        issue_result = result.results[0]
        self.assertIsNone(issue_result.jira_ticket)
        self.assertIn(
            ScanStep.LINKED_JIRA_KEY, [failure.step for failure in issue_result.step_failures]
        )
        self.assertEqual(issue_result.status, IssueCorrelationStatus.PARTIAL)

    async def test_retryable_failure_is_retried_once_then_succeeds(self) -> None:
        router = ScanSentryRouter(issue_count=1, jira_key="KAN-5")
        router.integrations_first_status["1001"] = 503
        sentry_source = create_sentry_source(router)
        github_source = github_source_with_commit()
        try:
            result = await scan_repository_for_correlations(
                repository_owner=REPO_OWNER,
                repository_name=REPO_NAME,
                sentry_project_slug="checkout-api",
                sentry_source=sentry_source,
                github_source=github_source,
            )
        finally:
            await sentry_source.aclose()

        issue_result = result.results[0]
        self.assertEqual(issue_result.jira_ticket, "KAN-5")
        self.assertEqual(issue_result.step_failures, ())
        integrations_requests = [
            request for request in router.requests if request.url.path.endswith("/integrations/")
        ]
        self.assertEqual(len(integrations_requests), 2)


def _matching_commit_evidence(
    *, path: str = "services/checkout.py", commit_sha: CommitSha = COMMIT_SHA
) -> tuple[Evidence, ...]:
    changed_file = Evidence(
        evidence_id=f"github:scan:commit:file:{commit_sha}",
        source=EvidenceSource.GITHUB,
        kind=EvidenceKind.COMMIT_CHANGED_FILE,
        provenance=EvidenceProvenance(
            source_reference=f"github:scan:commit:file:{commit_sha}",
            retrieved_at=FIXTURE_TIME,
        ),
        content=CommitChangedFileEvidenceContent(
            repository_owner=REPO_OWNER,
            repository_name=REPO_NAME,
            commit_sha=commit_sha,
            path=path,
            change_type=FileChangeType.MODIFIED,
            additions=7,
            deletions=1,
            changes=8,
            patch_available=True,
        ),
    )
    hunk = Evidence(
        evidence_id=f"github:scan:commit:hunk:{commit_sha}",
        source=EvidenceSource.GITHUB,
        kind=EvidenceKind.COMMIT_DIFF_HUNK,
        provenance=EvidenceProvenance(
            source_reference=f"github:scan:commit:hunk:{commit_sha}",
            retrieved_at=FIXTURE_TIME,
        ),
        content=CommitDiffHunkEvidenceContent(
            repository_owner=REPO_OWNER,
            repository_name=REPO_NAME,
            commit_sha=commit_sha,
            file_path=path,
            old_start=80,
            old_count=1,
            new_start=80,
            new_count=8,
            lines=(
                DiffLine(kind=DiffLineKind.CONTEXT, text="def create_order(cart):"),
                *(
                    DiffLine(kind=DiffLineKind.ADDITION, text=f"    line_{i} = cart['items'][{i}]")
                    for i in range(7)
                ),
            ),
        ),
    )
    return (changed_file, hunk)


def _matching_commit_fixture(
    *, path: str = "services/checkout.py", commit_sha: CommitSha = COMMIT_SHA
) -> tuple[GitHubCommitEvidenceRequest, Evidence, tuple[Evidence, ...]]:
    request = GitHubCommitEvidenceRequest(
        repository_owner=REPO_OWNER, repository_name=REPO_NAME, commit_sha=commit_sha
    )
    fixture_commit = COMMIT_EVIDENCE_FIXTURES[FIXTURE_COMMIT_REQUEST]
    commit = fixture_commit.model_copy(
        update={
            "evidence_id": f"github:scan:commit:{commit_sha}",
            "content": fixture_commit.content.model_copy(
                update={
                    "repository_owner": REPO_OWNER,
                    "repository_name": REPO_NAME,
                    "commit_sha": commit_sha,
                }
            ),
        }
    )
    return request, commit, _matching_commit_evidence(path=path, commit_sha=commit_sha)


def github_source_with_matching_commit(
    *, path: str = "services/checkout.py", commit_sha: CommitSha = COMMIT_SHA
) -> FakeGitHubCodeEvidenceSource:
    request, commit, changed_file_evidence = _matching_commit_fixture(
        path=path, commit_sha=commit_sha
    )
    return FakeGitHubCodeEvidenceSource(
        commit_fixtures={request: commit},
        commit_changed_file_fixtures={request: changed_file_evidence},
    )


class _MustNotBeCalledClient:
    provider = LLMProviderName.FAKE
    model = "must-not-be-called-fake"

    async def generate_typed(self, request):
        raise AssertionError(
            "the LLM boundary must not be reached when the deterministic gate "
            "should have skipped it"
        )


class _WrongFileHypothesisClient:
    provider = LLMProviderName.FAKE
    model = "wrong-file-fake"

    async def generate_typed(self, request: object) -> LLMStructuredResponse:
        facts = getattr(request.input, "facts", ())
        supporting = tuple(fact.fact_id for fact in facts)[:1]
        output = HypothesisGenerationOutput(
            candidates=(
                CandidateHypothesis(
                    hypothesis_id="hypothesis:wrong-file",
                    kind=HypothesisKind.CODE_CHANGE_MAY_HAVE_CONTRIBUTED,
                    subject="services/unrelated_module.py",
                    supporting_fact_ids=supporting or ("fact:placeholder",),
                ),
            )
        )
        return LLMStructuredResponse(output=output.model_dump(mode="json"))


class _FailingClient:
    provider = LLMProviderName.FAKE
    model = "failing-fake"

    async def generate_typed(self, request: object) -> LLMStructuredResponse:
        raise LLMProviderError(LLMProviderFailureCategory.UPSTREAM_UNAVAILABLE)


class _GroundedFixClient:
    provider = LLMProviderName.FAKE
    model = "grounded-fix-fake"

    async def generate_typed(self, request: object) -> LLMStructuredResponse:
        proposal_input = request.input
        output = {
            "candidate": {
                "finding_id": proposal_input.finding.finding_id,
                "file_path": proposal_input.finding.file_path,
                "corrected_hunk": proposal_input.original_hunk + "\n    # Proposed handling belongs here.",
                "failure_mechanism": "The observed indexed access can fail for an absent key.",
                "fix_strategy": "Handle the absent-key state in the selected hunk.",
                "explanation": "The suggested hunk addresses the state before the observed access continues.",
                "supporting_fact_ids": list(proposal_input.supporting_fact_ids),
                "supporting_evidence_ids": list(proposal_input.supporting_evidence_ids),
            }
        }
        return LLMStructuredResponse(output=output)


class _FailForOneIssueHypothesisClient:
    provider = LLMProviderName.FAKE
    model = "fail-first-issue-fake"

    def __init__(self, failing_short_id: str) -> None:
        self._failing_short_id = failing_short_id
        self._fallback = FakeLLMClient()

    async def generate_typed(self, request: object) -> LLMStructuredResponse:
        goal = getattr(request.input, "investigation_goal", "")
        if self._failing_short_id in goal:
            raise LLMProviderError(LLMProviderFailureCategory.UPSTREAM_UNAVAILABLE)
        return await self._fallback.generate_typed(request)


class CorrelationScanGroundedAnalysisTests(unittest.IsolatedAsyncioTestCase):
    async def test_grounded_path_produces_hypothesis_finding_and_recommendation(self) -> None:
        router = ScanSentryRouter(issue_count=1, jira_key="KAN-5")
        sentry_source = create_sentry_source(router)
        github_source = github_source_with_matching_commit()
        client = FakeLLMClient()
        try:
            result = await scan_repository_for_correlations(
                repository_owner=REPO_OWNER,
                repository_name=REPO_NAME,
                sentry_project_slug="checkout-api",
                sentry_source=sentry_source,
                github_source=github_source,
                hypothesis_client=client,
                code_diagnosis_client=client,
            )
        finally:
            await sentry_source.aclose()

        issue_result = result.results[0]
        self.assertEqual(issue_result.status, IssueCorrelationStatus.OK)
        analysis = issue_result.analysis
        self.assertEqual(analysis.status, IssueAnalysisStatus.COMPLETED)
        self.assertEqual(len(analysis.hypotheses), 1)
        self.assertEqual(analysis.hypotheses[0].subject, "services/checkout.py")
        self.assertTrue(analysis.code_findings)
        self.assertTrue(analysis.recommendations)


        finding_ids = {finding.finding_id for finding in analysis.code_findings}
        for recommendation in analysis.recommendations:
            self.assertIn(recommendation.finding_id, finding_ids)

    async def test_grounded_fix_is_additive_to_the_validated_diagnosis(self) -> None:
        router = ScanSentryRouter(issue_count=1, jira_key="KAN-5")
        sentry_source = create_sentry_source(router)
        try:
            result = await scan_repository_for_correlations(
                repository_owner=REPO_OWNER,
                repository_name=REPO_NAME,
                sentry_project_slug="checkout-api",
                sentry_source=sentry_source,
                github_source=github_source_with_matching_commit(),
                hypothesis_client=FakeLLMClient(),
                code_diagnosis_client=FakeLLMClient(),
                fix_proposal_client=_GroundedFixClient(),
            )
        finally:
            await sentry_source.aclose()

        analysis = result.results[0].analysis
        self.assertEqual(analysis.status, IssueAnalysisStatus.COMPLETED)
        self.assertEqual(analysis.fix_status.value, "available")
        self.assertEqual(len(analysis.proposed_fixes), 1)
        self.assertTrue(analysis.proposed_fixes[0].original_hunk)

    async def test_hypothesis_rejection_leaves_correlation_ok_and_skips_diagnosis(self) -> None:
        router = ScanSentryRouter(issue_count=1, jira_key="KAN-5")
        sentry_source = create_sentry_source(router)
        github_source = github_source_with_matching_commit()
        try:
            result = await scan_repository_for_correlations(
                repository_owner=REPO_OWNER,
                repository_name=REPO_NAME,
                sentry_project_slug="checkout-api",
                sentry_source=sentry_source,
                github_source=github_source,
                hypothesis_client=_WrongFileHypothesisClient(),
                code_diagnosis_client=_MustNotBeCalledClient(),
            )
        finally:
            await sentry_source.aclose()

        issue_result = result.results[0]
        self.assertEqual(issue_result.status, IssueCorrelationStatus.OK)
        analysis = issue_result.analysis
        self.assertEqual(analysis.status, IssueAnalysisStatus.NO_VALIDATED_HYPOTHESIS)
        self.assertEqual(analysis.hypotheses, ())
        self.assertEqual(analysis.code_findings, ())

    async def test_hypothesis_provider_failure_does_not_stop_other_issues(self) -> None:
        router = ScanSentryRouter(issue_count=2, jira_key="KAN-5")
        sentry_source = create_sentry_source(router)
        github_source = github_source_with_matching_commit()
        client = _FailForOneIssueHypothesisClient(failing_short_id="CHECKOUT-1001")
        try:
            result = await scan_repository_for_correlations(
                repository_owner=REPO_OWNER,
                repository_name=REPO_NAME,
                sentry_project_slug="checkout-api",
                sentry_source=sentry_source,
                github_source=github_source,
                hypothesis_client=client,
                code_diagnosis_client=client,
            )
        finally:
            await sentry_source.aclose()

        self.assertEqual(len(result.results), 2)
        failed_issue = next(
            item for item in result.results if item.sentry_short_id == "CHECKOUT-1001"
        )
        continued_issue = next(
            item for item in result.results if item.sentry_short_id == "CHECKOUT-1002"
        )


        self.assertEqual(failed_issue.status, IssueCorrelationStatus.OK)
        self.assertEqual(
            failed_issue.analysis.status, IssueAnalysisStatus.HYPOTHESIS_GENERATION_FAILED
        )
        self.assertEqual(continued_issue.status, IssueCorrelationStatus.OK)
        self.assertEqual(continued_issue.analysis.status, IssueAnalysisStatus.COMPLETED)

    async def test_code_diagnosis_failure_preserves_hypothesis_but_no_finding(self) -> None:
        router = ScanSentryRouter(issue_count=1, jira_key="KAN-5")
        sentry_source = create_sentry_source(router)
        github_source = github_source_with_matching_commit()
        try:
            result = await scan_repository_for_correlations(
                repository_owner=REPO_OWNER,
                repository_name=REPO_NAME,
                sentry_project_slug="checkout-api",
                sentry_source=sentry_source,
                github_source=github_source,
                hypothesis_client=FakeLLMClient(),
                code_diagnosis_client=_FailingClient(),
            )
        finally:
            await sentry_source.aclose()

        issue_result = result.results[0]
        self.assertEqual(issue_result.status, IssueCorrelationStatus.OK)
        analysis = issue_result.analysis
        self.assertEqual(analysis.status, IssueAnalysisStatus.CODE_FINDING_UNAVAILABLE)
        self.assertEqual(len(analysis.hypotheses), 1)
        self.assertEqual(analysis.code_findings, ())
        self.assertEqual(analysis.recommendations, ())

    async def test_insufficient_facts_skips_the_llm_boundary_entirely(self) -> None:
        router = ScanSentryRouter(issue_count=1, jira_key="KAN-5")
        sentry_source = create_sentry_source(router)


        github_source = github_source_with_matching_commit(path="services/unrelated.py")
        try:
            result = await scan_repository_for_correlations(
                repository_owner=REPO_OWNER,
                repository_name=REPO_NAME,
                sentry_project_slug="checkout-api",
                sentry_source=sentry_source,
                github_source=github_source,
                hypothesis_client=_MustNotBeCalledClient(),
                code_diagnosis_client=_MustNotBeCalledClient(),
            )
        finally:
            await sentry_source.aclose()

        issue_result = result.results[0]
        self.assertEqual(issue_result.status, IssueCorrelationStatus.OK)
        self.assertEqual(
            issue_result.analysis.status, IssueAnalysisStatus.INSUFFICIENT_EVIDENCE
        )

    async def test_two_issues_in_one_scan_never_share_facts_or_hypotheses(self) -> None:
        router = ScanSentryRouter(issue_count=2, jira_key="KAN-5")
        other_commit_sha: CommitSha = "c" * 40
        router.detail_overrides["1002"] = httpx.Response(
            200,
            json=issue_detail(
                id="1002",
                shortId="CHECKOUT-1002",
                firstRelease={"version": other_commit_sha, "lastCommit": None},
            ),
        )
        sentry_source = create_sentry_source(router)


        request_a, commit_a, evidence_a = _matching_commit_fixture()
        request_b, commit_b, evidence_b = _matching_commit_fixture(
            path="services/billing.py", commit_sha=other_commit_sha
        )
        github_source = FakeGitHubCodeEvidenceSource(
            commit_fixtures={request_a: commit_a, request_b: commit_b},
            commit_changed_file_fixtures={request_a: evidence_a, request_b: evidence_b},
        )
        client = FakeLLMClient()
        try:
            result = await scan_repository_for_correlations(
                repository_owner=REPO_OWNER,
                repository_name=REPO_NAME,
                sentry_project_slug="checkout-api",
                sentry_source=sentry_source,
                github_source=github_source,
                hypothesis_client=client,
                code_diagnosis_client=client,
            )
        finally:
            await sentry_source.aclose()

        matching_issue = next(
            item for item in result.results if item.sentry_short_id == "CHECKOUT-1001"
        )
        unrelated_issue = next(
            item for item in result.results if item.sentry_short_id == "CHECKOUT-1002"
        )
        self.assertEqual(matching_issue.analysis.status, IssueAnalysisStatus.COMPLETED)
        self.assertEqual(
            matching_issue.analysis.hypotheses[0].subject, "services/checkout.py"
        )


        self.assertEqual(
            unrelated_issue.analysis.status, IssueAnalysisStatus.INSUFFICIENT_EVIDENCE
        )
        self.assertEqual(unrelated_issue.analysis.hypotheses, ())
        matching_fact_ids = set(matching_issue.fact_ids)
        unrelated_fact_ids = set(unrelated_issue.fact_ids)
        self.assertTrue(matching_fact_ids.isdisjoint(unrelated_fact_ids))

    async def test_correlation_scan_module_never_imports_planner_or_executor(self) -> None:
        import app.workflows.correlation_scan as module

        forbidden_names = {
            "TypedLLMPlanner",
            "PlanValidator",
            "AdaptiveInvestigationRuntime",
            "AgentExecutor",
        }
        self.assertFalse(forbidden_names & set(dir(module)))


if __name__ == "__main__":
    unittest.main()
