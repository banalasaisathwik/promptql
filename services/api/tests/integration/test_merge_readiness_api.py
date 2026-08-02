pass

import unittest

from fastapi.testclient import TestClient

from app.api.v1.connector_router import (
    get_github_connector,
    get_jira_connector,
    get_merge_readiness_workflow,
)
from app.connectors.errors import ConnectorUnavailableError
from app.connectors.fakes import FakeGitHubConnector, FakeJiraConnector
from app.connectors.fixture_catalog import FAILED_CI_REQUEST, MERGE_READY_REQUEST
from app.connectors.models import ConnectorRequest, GitHubPullRequest, JiraIssue
from app.main import app
from app.runtime import InMemoryRunRepository, MergeReadinessRun
from app.workflows import MergeReadinessWorkflowService


class UnavailableJiraConnector:
    def get_issue_for_pull_request(self, _request: ConnectorRequest) -> JiraIssue:
        raise ConnectorUnavailableError("jira")


class FailingGitHubConnector:
    def get_pull_request(self, _request: ConnectorRequest) -> GitHubPullRequest:
        raise RuntimeError("secret-connector-detail")


class RecordingWorkflow:
    pass

    def __init__(self, run: MergeReadinessRun) -> None:
        self.run = run
        self.requests: list[ConnectorRequest] = []

    def execute(self, request: ConnectorRequest) -> MergeReadinessRun:
        self.requests.append(request)
        return self.run


def provide_unavailable_jira_connector() -> UnavailableJiraConnector:
    return UnavailableJiraConnector()


def provide_failing_github_connector() -> FailingGitHubConnector:
    return FailingGitHubConnector()


def completed_ready_run() -> MergeReadinessRun:
    return MergeReadinessWorkflowService(
        FakeGitHubConnector(),
        FakeJiraConnector(),
        InMemoryRunRepository(),
    ).execute(MERGE_READY_REQUEST)


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

    def test_failed_ci_returns_completed_blocked_run(self) -> None:
        response = self.post_request(FAILED_CI_REQUEST)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["result"]["decision"], "blocked")
        self.assertIsNone(body["error"])
        self.assertEqual(len(body["steps"]), 3)

    def test_merge_ready_facts_return_completed_ready_run(self) -> None:
        response = self.post_request(MERGE_READY_REQUEST)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["result"]["decision"], "ready")

    def test_missing_jira_evidence_completes_with_unknown(self) -> None:
        app.dependency_overrides[get_jira_connector] = (
            provide_unavailable_jira_connector
        )

        response = self.post_request(MERGE_READY_REQUEST)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["result"]["decision"], "unknown")
        self.assertIsNone(body["jira"])

    def test_unexpected_connector_failure_returns_typed_500_run(self) -> None:
        app.dependency_overrides[get_github_connector] = (
            provide_failing_github_connector
        )

        response = self.post_request(MERGE_READY_REQUEST)

        self.assertEqual(response.status_code, 500)
        run = MergeReadinessRun.model_validate(response.json())
        self.assertEqual(run.status.value, "failed")
        self.assertIsNone(run.result)
        self.assertIsNotNone(run.run_id)
        self.assertIsNotNone(run.started_at)
        self.assertIsNotNone(run.completed_at)
        self.assertEqual(run.steps[-1].status.value, "failed")
        self.assertNotIn("secret-connector-detail", run.error.message)

    def test_route_delegates_to_workflow_service(self) -> None:
        workflow = RecordingWorkflow(completed_ready_run())
        app.dependency_overrides[get_merge_readiness_workflow] = lambda: workflow

        response = self.post_request(MERGE_READY_REQUEST)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(workflow.requests, [MERGE_READY_REQUEST])

    def test_success_response_matches_declared_schema(self) -> None:
        response = self.post_request(MERGE_READY_REQUEST)

        self.assertEqual(response.status_code, 200)
        validated = MergeReadinessRun.model_validate(response.json())
        self.assertEqual(validated.request, MERGE_READY_REQUEST)
        self.assertEqual(validated.result.decision.value, "ready")

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

    def test_invalid_input_returns_422_before_workflow_execution(self) -> None:
        workflow = RecordingWorkflow(completed_ready_run())
        app.dependency_overrides[get_merge_readiness_workflow] = lambda: workflow

        response = self.client.post(
            "/v1/pull-request-merge-readiness",
            json={
                "repository_owner": "acme",
                "repository_name": "analytics",
                "pr_number": 0,
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(workflow.requests, [])


if __name__ == "__main__":
    unittest.main()
