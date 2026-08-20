import asyncio
import unittest
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.v1.connector_router import (
    get_investigation_workflow,
    get_run_repository,
)
from app.api.v1.models import InvestigationResponse
from app.explanations import FakeLLMClient
from app.investigations.models import InvestigationRequest
from app.main import app
from app.runtime import InMemoryRunRepository
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
            incident_summary="Checkout failures increased.",
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
        self.assertIsNotNone(parsed.result)
        self.assertEqual(parsed.result.supported_hypotheses, ())

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


if __name__ == "__main__":
    unittest.main()
