pass

import unittest

from fastapi.testclient import TestClient

from app.api.v1.connector_router import get_jira_connector
from app.connectors.errors import ConnectorUnavailableError
from app.connectors.fixture_catalog import (
    FAILED_CI_REQUEST,
    MERGE_READY_REQUEST,
)
from app.connectors.models import ConnectorRequest, JiraIssue
from app.inspection.models import PullRequestMergeReadiness
from app.main import app


class UnavailableJiraConnector:
    pass

    def get_issue_for_pull_request(self, _request: ConnectorRequest) -> JiraIssue:
        raise ConnectorUnavailableError("jira")


def provide_unavailable_jira_connector() -> UnavailableJiraConnector:
    pass

    return UnavailableJiraConnector()


class MergeReadinessApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def tearDown(self) -> None:


        app.dependency_overrides.clear()

    def post_request(self, request: ConnectorRequest):
        return self.client.post(
            "/v1/pull-request-merge-readiness",
            json=request.model_dump(mode="json"),
        )

    def test_failed_ci_returns_blocked_with_policy_details(self) -> None:
        response = self.post_request(FAILED_CI_REQUEST)

        self.assertEqual(response.status_code, 200)
        policy_result = response.json()["policy_result"]
        self.assertEqual(policy_result["decision"], "blocked")
        self.assertEqual(policy_result["reason_code"], "ci_check_failed")
        self.assertIn(
            "ci_check_failed",
            [blocker["reason_code"] for blocker in policy_result["blockers"]],
        )
        self.assertTrue(policy_result["pending_actions"])
        self.assertTrue(policy_result["evidence_references"])

    def test_merge_ready_facts_return_ready(self) -> None:
        response = self.post_request(MERGE_READY_REQUEST)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["policy_result"]["decision"], "ready")

    def test_missing_required_jira_evidence_returns_unknown(self) -> None:
        app.dependency_overrides[get_jira_connector] = (
            provide_unavailable_jira_connector
        )

        response = self.post_request(MERGE_READY_REQUEST)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsNone(body["jira"])
        self.assertEqual(body["policy_result"]["decision"], "unknown")
        self.assertTrue(body["policy_result"]["missing_information"])

    def test_verified_blocker_wins_when_jira_is_unavailable(self) -> None:
        app.dependency_overrides[get_jira_connector] = (
            provide_unavailable_jira_connector
        )

        response = self.post_request(FAILED_CI_REQUEST)

        self.assertEqual(response.status_code, 200)
        policy_result = response.json()["policy_result"]
        self.assertEqual(policy_result["decision"], "blocked")
        self.assertTrue(policy_result["blockers"])
        self.assertTrue(policy_result["missing_information"])

    def test_response_matches_declared_pydantic_schema(self) -> None:
        response = self.post_request(MERGE_READY_REQUEST)

        self.assertEqual(response.status_code, 200)
        validated = PullRequestMergeReadiness.model_validate(response.json())
        self.assertEqual(validated.request, MERGE_READY_REQUEST)
        self.assertEqual(validated.policy_result.decision.value, "ready")

    def test_unknown_fixture_keeps_structured_not_found_error(self) -> None:
        response = self.post_request(
            ConnectorRequest(
                repository_owner="acme",
                repository_name="analytics",
                pr_number=404,
            )
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "fixture_not_found")

    def test_invalid_request_keeps_fastapi_validation_error(self) -> None:
        response = self.client.post(
            "/v1/pull-request-merge-readiness",
            json={
                "repository_owner": "acme",
                "repository_name": "analytics",
                "pr_number": 0,
            },
        )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
