import asyncio
import unittest
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.v1.connector_router import (
    get_github_connector,
    get_jira_connector,
    get_merge_readiness_explanation_service,
    get_merge_readiness_workflow,
    get_run_repository,
)
from app.api.v1.models import MergeReadinessResponse
from app.connectors.errors import ConnectorUnavailableError
from app.connectors.fakes import FakeGitHubConnector, FakeJiraConnector
from app.connectors.fixture_catalog import FAILED_CI_REQUEST, MERGE_READY_REQUEST
from app.connectors.models import ConnectorRequest, GitHubPullRequest, JiraIssue
from app.explanations import (
    LLMStructuredResponse,
    MergeReadinessExplanationService,
)
from app.main import app
from app.runtime import (
    InMemoryRunRepository,
    MergeReadinessRun,
    RunPersistenceError,
)
from app.workflows import MergeReadinessWorkflowService


class UnavailableJiraConnector:
    async def get_issue(self, _issue_key: str) -> JiraIssue:
        raise ConnectorUnavailableError("jira")


class FailingGitHubConnector:
    async def get_pull_request(
        self,
        _request: ConnectorRequest,
    ) -> GitHubPullRequest:
        raise RuntimeError("secret-connector-detail")


class AlteredExplanationClient:
    async def generate_structured(self, explanation_input):
        return LLMStructuredResponse(
            output={
                "decision": explanation_input.decision.value,
                "summary": "Unapproved generated wording must not reach the UI.",
                "reasons": ("An unsupported claim.",),
                "recommended_actions": (),
            }
        )


class RecordingWorkflow:
    def __init__(self, run: MergeReadinessRun) -> None:
        self.run = run
        self.requests: list[ConnectorRequest] = []

    async def execute(self, request: ConnectorRequest) -> MergeReadinessRun:
        self.requests.append(request)
        return self.run


class UnavailableRunRepository:
    def save(self, _run: MergeReadinessRun) -> None:
        raise RunPersistenceError("Runtime persistence is unavailable.")

    def get(self, _run_id):
        raise RunPersistenceError("Runtime persistence is unavailable.")


def provide_unavailable_jira_connector() -> UnavailableJiraConnector:
    return UnavailableJiraConnector()


def provide_failing_github_connector() -> FailingGitHubConnector:
    return FailingGitHubConnector()


def completed_ready_run() -> MergeReadinessRun:
    return asyncio.run(
        MergeReadinessWorkflowService(
            FakeGitHubConnector(),
            FakeJiraConnector(),
            InMemoryRunRepository(),
        ).execute(MERGE_READY_REQUEST)
    )


class MergeReadinessApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def setUp(self) -> None:
        self.repository = InMemoryRunRepository()
        app.dependency_overrides[get_run_repository] = lambda: self.repository

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
        run = MergeReadinessResponse.model_validate(response.json())
        self.assertEqual(run.status.value, "failed")
        self.assertIsNone(run.result)
        self.assertIsNotNone(run.run_id)
        self.assertIsNotNone(run.started_at)
        self.assertIsNotNone(run.completed_at)
        self.assertEqual(run.steps[-1].status.value, "failed")
        self.assertNotIn("secret-connector-detail", run.error.message)
        self.assertIsNone(run.explanation)
        self.assertIsNone(run.explanation_error)

    def test_route_delegates_to_workflow_service(self) -> None:
        workflow = RecordingWorkflow(completed_ready_run())
        app.dependency_overrides[get_merge_readiness_workflow] = lambda: workflow

        response = self.post_request(MERGE_READY_REQUEST)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(workflow.requests, [MERGE_READY_REQUEST])

    def test_success_response_matches_declared_schema(self) -> None:
        response = self.post_request(MERGE_READY_REQUEST)

        self.assertEqual(response.status_code, 200)
        validated = MergeReadinessResponse.model_validate(response.json())
        self.assertEqual(validated.request, MERGE_READY_REQUEST)
        self.assertEqual(validated.result.decision.value, "ready")
        self.assertEqual(validated.explanation.decision.value, "ready")
        self.assertIsNone(validated.explanation_error)

    def test_blocked_and_unknown_responses_include_validated_explanations(self) -> None:
        blocked = self.post_request(FAILED_CI_REQUEST)
        app.dependency_overrides[get_jira_connector] = (
            provide_unavailable_jira_connector
        )
        unknown = self.post_request(MERGE_READY_REQUEST)

        self.assertEqual(
            blocked.json()["explanation"]["decision"],
            blocked.json()["result"]["decision"],
        )
        self.assertEqual(
            unknown.json()["explanation"]["decision"],
            unknown.json()["result"]["decision"],
        )

    def test_rejected_explanation_does_not_change_completed_policy_result(self) -> None:
        app.dependency_overrides[get_merge_readiness_explanation_service] = (
            lambda: MergeReadinessExplanationService(AlteredExplanationClient())
        )

        response = self.post_request(MERGE_READY_REQUEST)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["result"]["decision"], "ready")
        self.assertIsNone(body["explanation"])
        self.assertEqual(
            body["explanation_error"]["code"],
            "validation_failed",
        )
        self.assertNotIn("Unapproved generated wording", response.text)
        stored = self.repository.get(UUID(body["run_id"]))
        self.assertEqual(stored.result.decision.value, "ready")

    def test_completed_run_can_be_retrieved_by_run_id(self) -> None:
        created_response = self.post_request(MERGE_READY_REQUEST)
        run_id = created_response.json()["run_id"]

        retrieval_response = self.client.get(f"/v1/runs/{run_id}")

        self.assertEqual(retrieval_response.status_code, 200)
        self.assertEqual(retrieval_response.json(), created_response.json())

    def test_failed_run_can_be_retrieved_as_a_resource(self) -> None:
        app.dependency_overrides[get_github_connector] = (
            provide_failing_github_connector
        )
        created_response = self.post_request(MERGE_READY_REQUEST)
        run_id = created_response.json()["run_id"]

        retrieval_response = self.client.get(f"/v1/runs/{run_id}")

        self.assertEqual(created_response.status_code, 500)
        self.assertEqual(retrieval_response.status_code, 200)
        self.assertEqual(retrieval_response.json()["status"], "failed")

    def test_unknown_run_returns_typed_404(self) -> None:
        response = self.client.get(
            "/v1/runs/00000000-0000-0000-0000-000000000001"
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "run_not_found")

    def test_unavailable_persistence_returns_sanitized_503(self) -> None:
        app.dependency_overrides[get_run_repository] = UnavailableRunRepository

        response = self.post_request(MERGE_READY_REQUEST)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["code"],
            "runtime_persistence_unavailable",
        )
        self.assertIsNone(response.json()["run_id"])

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
