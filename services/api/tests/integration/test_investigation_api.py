import asyncio
import time
import unittest
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.v1.connector_router import (
    get_investigation_workflow,
    get_run_repository,
)
from app.api.v1.models import InvestigationResponse
from app.explanations import FakeLLMClient
from app.investigations.models import InvestigationRequest
from app.main import app
from app.runtime import InMemoryRunRepository, RunStateConflictError, RunStatus
from app.runtime.investigation_models import MAX_FOLLOW_UPS_PER_CASE, InvestigationRun
from app.workflows import InvestigationWorkflowService


class InvestigationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def setUp(self) -> None:
        self.repository = InMemoryRunRepository()
        app.dependency_overrides[get_run_repository] = lambda: self.repository

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def request(self) -> InvestigationRequest:
        return InvestigationRequest(
            repository_owner="octo-org",
            repository_name="analytics",
            question="Why did checkout failures increase?",
            incident_reference="incident:checkout-500",
        )

    def test_completed_investigation_response_exposes_typed_state(self) -> None:
        workflow = InvestigationWorkflowService(self.repository, FakeLLMClient())
        pending = asyncio.run(workflow.create_persisted_run(self.request()))
        completed = asyncio.run(workflow.continue_persisted_run(pending))

        response = self.client.get(f"/v1/runs/{completed.run_id}")

        self.assertEqual(response.status_code, 200)
        parsed = InvestigationResponse.model_validate(response.json())
        self.assertEqual(parsed.workflow_name, "investigation")
        self.assertIsNotNone(parsed.state)
        self.assertTrue(parsed.results)
        self.assertEqual(parsed.results[-1].supported_hypotheses, ())

    def test_investigation_start_returns_accepted_run_id(self) -> None:
        workflow = InvestigationWorkflowService(self.repository, FakeLLMClient())
        app.dependency_overrides[get_investigation_workflow] = lambda: workflow

        response = self.client.post(
            "/v1/investigations",
            json=self.request().model_dump(mode="json"),
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "pending")
        self.assertIsNotNone(self.repository.get(UUID(response.json()["run_id"])))

    def test_investigation_without_a_grounding_reference_is_rejected(self) -> None:
        workflow = InvestigationWorkflowService(self.repository, FakeLLMClient())
        app.dependency_overrides[get_investigation_workflow] = lambda: workflow

        response = self.client.post(
            "/v1/investigations",
            json={
                "repository_owner": "octo-org",
                "repository_name": "analytics",
                "question": "Why did checkout failures increase?",
            },
        )

        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertTrue(
            any(
                "At least one of incident_reference, pull_request_number, "
                "or deployment_reference is required" in error["msg"]
                for error in detail
            ),
            detail,
        )

    def test_checkout_fixture_request_completes_with_persisted_evidence(self) -> None:
        workflow = InvestigationWorkflowService(self.repository, FakeLLMClient())
        request = InvestigationRequest(
            repository_owner="octo-org",
            repository_name="analytics",
            question="Why did checkout start returning 500s after the latest deployment?",
            incident_reference="incident:checkout-500",
            deployment_reference="deployment:1042",
            pull_request_number=42,
            service="checkout-api",
            environment="production",
        )

        pending = asyncio.run(workflow.create_persisted_run(request))
        completed = asyncio.run(workflow.continue_persisted_run(pending))

        self.assertEqual(completed.status, "completed")
        self.assertIsNotNone(completed.state)
        self.assertTrue(completed.state.working_memory.evidence)
        self.assertGreaterEqual(len(completed.state.execution_state.rounds), 2)
        self.assertTrue(completed.state.working_memory.facts)
        self.assertEqual(len(completed.state.working_memory.validated_hypotheses), 1)
        self.assertEqual(len(completed.results[-1].supported_hypotheses), 1)
        self.assertEqual(len(completed.state.working_memory.validated_code_findings), 1)
        self.assertIsNotNone(completed.state.execution_state.code_diagnosis_metadata)
        self.assertEqual(completed.state.execution_state.rejected_code_finding_count, 0)
        self.assertEqual(len(completed.state.working_memory.developer_recommendations), 3)
        self.assertEqual(len(completed.results[-1].code_findings), 1)
        self.assertEqual(len(completed.results[-1].recommendations), 3)
        self.assertIn("suspected contributor", completed.results[-1].code_findings[0].statement)


class _CapEnforcingRepository:
    def __init__(self, inner: InMemoryRunRepository) -> None:
        self._inner = inner

    def save(self, run) -> None:
        if isinstance(run, InvestigationRun) and run.status is RunStatus.RUNNING:
            stored = self._inner.get(run.run_id)
            if (
                stored is not None
                and stored.status is RunStatus.COMPLETED
                and stored.follow_up_count >= MAX_FOLLOW_UPS_PER_CASE
            ):
                raise RunStateConflictError(
                    "This investigation has reached its follow-up limit.",
                    run.run_id,
                )
        self._inner.save(run)

    def get(self, run_id):
        return self._inner.get(run_id)


class InvestigationFollowUpApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def setUp(self) -> None:
        self.repository = InMemoryRunRepository()
        app.dependency_overrides[get_run_repository] = lambda: self.repository

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def request(self) -> InvestigationRequest:
        return InvestigationRequest(
            repository_owner="octo-org",
            repository_name="analytics",
            question="Why did checkout failures increase?",
            incident_reference="incident:checkout-500",
        )

    def _completed_run(self, workflow: InvestigationWorkflowService) -> InvestigationRun:
        pending = asyncio.run(workflow.create_persisted_run(self.request()))
        return asyncio.run(workflow.continue_persisted_run(pending))

    def _await_status(self, run_id: UUID, status: str, attempts: int = 40) -> dict:
        body = {}
        for _ in range(attempts):
            response = self.client.get(f"/v1/runs/{run_id}")
            body = response.json()
            if body["status"] == status:
                return body
            time.sleep(0.05)
        self.fail(f"run {run_id} never reached status {status!r}; last body: {body}")

    def test_follow_up_starts_a_reopened_run_and_appends_a_second_result(self) -> None:
        workflow = InvestigationWorkflowService(self.repository, FakeLLMClient())
        app.dependency_overrides[get_investigation_workflow] = lambda: workflow
        completed = self._completed_run(workflow)

        response = self.client.post(
            f"/v1/investigations/{completed.run_id}/follow-up",
            json={"question": "What about the deployment?"},
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "running")
        self.assertEqual(response.json()["run_id"], str(completed.run_id))

        body = self._await_status(completed.run_id, "completed")
        parsed = InvestigationResponse.model_validate(body)
        self.assertEqual(len(parsed.results), 2)
        self.assertEqual(parsed.results[0], completed.results[0])
        self.assertEqual(parsed.follow_up_count, 1)

    def test_follow_up_returns_404_for_an_unknown_run(self) -> None:
        workflow = InvestigationWorkflowService(self.repository, FakeLLMClient())
        app.dependency_overrides[get_investigation_workflow] = lambda: workflow

        response = self.client.post(
            f"/v1/investigations/{uuid4()}/follow-up",
            json={"question": "Anything else?"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "run_not_found")

    def test_follow_up_rejects_a_run_that_is_not_completed(self) -> None:
        workflow = InvestigationWorkflowService(self.repository, FakeLLMClient())
        app.dependency_overrides[get_investigation_workflow] = lambda: workflow
        pending = asyncio.run(workflow.create_persisted_run(self.request()))

        response = self.client.post(
            f"/v1/investigations/{pending.run_id}/follow-up",
            json={"question": "Anything else?"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "runtime_state_conflict")

    def test_a_fourth_reopen_attempt_is_rejected_cleanly_not_as_a_raw_exception(self) -> None:
        workflow_over_repository = InvestigationWorkflowService(
            self.repository, FakeLLMClient()
        )
        completed = self._completed_run(workflow_over_repository)
        at_cap = self.repository.get(completed.run_id).model_copy(
            update={"follow_up_count": MAX_FOLLOW_UPS_PER_CASE}
        )
        self.repository._runs[at_cap.run_id] = at_cap

        capped_repository = _CapEnforcingRepository(self.repository)
        app.dependency_overrides[get_run_repository] = lambda: capped_repository
        workflow = InvestigationWorkflowService(capped_repository, FakeLLMClient())
        app.dependency_overrides[get_investigation_workflow] = lambda: workflow

        response = self.client.post(
            f"/v1/investigations/{completed.run_id}/follow-up",
            json={"question": "One more time?"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "runtime_state_conflict")
        self.assertIn("follow-up limit", response.json()["message"])


if __name__ == "__main__":
    unittest.main()
