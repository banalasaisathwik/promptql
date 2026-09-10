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
from app.investigations import (
    CommitChangedFileEvidenceContent,
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
    EvidenceSource,
    FileChangeType,
)
from app.workflows.correlation_scan import (
    IssueCorrelationStatus,
    RepositoryCorrelationScanResult,
    ScanStep,
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


if __name__ == "__main__":
    unittest.main()
