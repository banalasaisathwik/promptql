import os
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api.v1.auth_router import get_current_user_optional
from app.api.v1.connector_router import get_github_code_evidence_source
from app.api.v1.credentials_router import get_credential_repository
from app.api.v1.correlation_scan_router import get_sentry_source_for_scan
from app.auth import CredentialProvider, InMemoryCredentialRepository, InMemoryUserRepository
from app.connectors.errors import SentryUpstreamUnavailableError
from app.connectors.github_code_fakes import FakeGitHubCodeEvidenceSource
from app.connectors.models import (
    FailureLocationEvidenceRequest,
    JiraIssueKey,
    SentryOpenIssue,
    SentryOpenIssuesRequest,
)
from app.investigations import Evidence, EvidenceKind, EvidenceProvenance, EvidenceSource, StackFrameEvidenceContent
from app.main import app


class FakeSentryScanSource:
    def __init__(
        self,
        *,
        open_issues: tuple[SentryOpenIssue, ...] = (),
        jira_key: JiraIssueKey | None = None,
        commit_sha: str | None = None,
        list_open_issues_error: Exception | None = None,
    ) -> None:
        self._open_issues = open_issues
        self._jira_key = jira_key
        self._commit_sha = commit_sha
        self._list_open_issues_error = list_open_issues_error

    async def list_open_issues(
        self, request: SentryOpenIssuesRequest
    ) -> tuple[SentryOpenIssue, ...]:
        if self._list_open_issues_error is not None:
            raise self._list_open_issues_error
        return self._open_issues

    async def get_linked_jira_key(self, issue_id: str) -> JiraIssueKey | None:
        return self._jira_key

    async def get_failure_location_evidence(
        self, request: FailureLocationEvidenceRequest
    ) -> Evidence:
        return Evidence(
            evidence_id=f"sentry:issue:{request.incident_reference}:failure-location",
            source=EvidenceSource.INCIDENT,
            kind=EvidenceKind.STACK_FRAME,
            provenance=EvidenceProvenance(
                source_reference=f"sentry:issue:{request.incident_reference}",
                retrieved_at=datetime(2026, 8, 17, 12, 0, tzinfo=UTC),
            ),
            content=StackFrameEvidenceContent(
                service="checkout-api",
                file_path="services/checkout.py",
                function_name="create_order",
                line_number=87,
            ),
        )

    async def get_issue_commit_sha(self, issue_id: str) -> str | None:
        return self._commit_sha


ISSUE = SentryOpenIssue(
    issue_id="1001",
    short_id="CHECKOUT-1",
    project_slug="checkout-api",
    first_seen=datetime(2026, 8, 17, 11, 40, tzinfo=UTC),
    last_seen=datetime(2026, 8, 17, 11, 50, tzinfo=UTC),
)


class CorrelationScanApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {"PROMPTQL_CREDENTIAL_ENCRYPTION_KEY": Fernet.generate_key().decode()},
            clear=False,
        )
        self.environment.start()
        self.user_repository = InMemoryUserRepository()
        self.current_user = self.user_repository.create_user(
            "scan@example.com", "correct horse battery staple"
        )
        self.demo_user = self.user_repository.create_user(
            "demo@example.com", "correct horse battery staple", is_demo=True
        )
        self.credential_repository = InMemoryCredentialRepository()
        self.active_user = self.current_user
        app.dependency_overrides[get_current_user_optional] = (
            lambda: self.active_user
        )
        app.dependency_overrides[get_credential_repository] = (
            lambda: self.credential_repository
        )
        app.dependency_overrides[get_github_code_evidence_source] = (
            lambda: FakeGitHubCodeEvidenceSource()
        )

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.environment.stop()

    @staticmethod
    def _request_body() -> dict[str, str]:
        return {
            "repository_owner": "octo-org",
            "repository_name": "analytics",
            "sentry_project_slug": "checkout-api",
        }

    def _override_sentry_source(self, source: FakeSentryScanSource) -> None:
        async def override():
            yield source

        app.dependency_overrides[get_sentry_source_for_scan] = override

    def test_anonymous_caller_gets_409_before_any_connector_call(self) -> None:
        self.active_user = None

        response = self.client.post("/v1/correlation-scans", json=self._request_body())

        self.assertEqual(response.status_code, 409)

    def test_demo_user_gets_409(self) -> None:
        self.active_user = self.demo_user

        response = self.client.post("/v1/correlation-scans", json=self._request_body())

        self.assertEqual(response.status_code, 409)

    def test_authenticated_user_without_sentry_credential_gets_409(self) -> None:
        response = self.client.post("/v1/correlation-scans", json=self._request_body())

        self.assertEqual(response.status_code, 409)

    def test_successful_scan_returns_full_result(self) -> None:
        self.credential_repository.store_credential(
            self.current_user.id, CredentialProvider.SENTRY, "test-sentry-token"
        )
        self._override_sentry_source(
            FakeSentryScanSource(open_issues=(ISSUE,), jira_key="KAN-5", commit_sha=None)
        )

        response = self.client.post("/v1/correlation-scans", json=self._request_body())

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["repository_owner"], "octo-org")
        self.assertEqual(body["total_open_issues_found"], 1)
        self.assertEqual(body["issues_scanned"], 1)
        self.assertFalse(body["truncated"])
        self.assertEqual(len(body["results"]), 1)
        result = body["results"][0]
        self.assertEqual(result["sentry_issue_id"], "1001")
        self.assertEqual(result["jira_ticket"], "KAN-5")
        self.assertIsNone(result["commit_sha"])
        self.assertEqual(result["status"], "ok")

    def test_sentry_connector_error_maps_to_typed_upstream_failure(self) -> None:
        self.credential_repository.store_credential(
            self.current_user.id, CredentialProvider.SENTRY, "test-sentry-token"
        )
        self._override_sentry_source(
            FakeSentryScanSource(list_open_issues_error=SentryUpstreamUnavailableError())
        )

        response = self.client.post("/v1/correlation-scans", json=self._request_body())

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "correlation_scan_upstream_failed")
        self.assertNotIn("token", response.text.lower())

    def test_missing_sentry_project_slug_is_rejected_before_any_call(self) -> None:
        self.credential_repository.store_credential(
            self.current_user.id, CredentialProvider.SENTRY, "test-sentry-token"
        )
        self._override_sentry_source(FakeSentryScanSource())

        response = self.client.post(
            "/v1/correlation-scans",
            json={"repository_owner": "octo-org", "repository_name": "analytics"},
        )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
