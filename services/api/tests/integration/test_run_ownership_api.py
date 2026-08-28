import asyncio
import unittest
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.v1.auth_router import get_current_user_optional
from app.api.v1.connector_router import (
    get_investigation_workflow,
    get_live_run_task_registry,
    get_run_repository,
)
from app.api.v1.live_events_router import stream_run_events
from app.auth import InMemoryUserRepository, User
from app.explanations import FakeLLMClient
from app.investigations.models import InvestigationRequest
from app.main import app
from app.runtime import InMemoryRunRepository
from app.workflows import InvestigationWorkflowService


class _HoldingLiveRunTaskRegistry:
    def start(self, coroutine: object) -> None:
        coroutine.close()


class RunOwnershipApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app, client=("run-ownership", 50000))

    def setUp(self) -> None:
        self.repository = InMemoryRunRepository()
        self.user_repository = InMemoryUserRepository()
        self.user_a = self.user_repository.create_user(
            "owner@example.com", "correct horse battery staple"
        )
        self.user_b = self.user_repository.create_user(
            "other@example.com", "correct horse battery staple"
        )
        self.workflow = InvestigationWorkflowService(self.repository, FakeLLMClient())

        def current_user(request: Request) -> User | None:
            return {
                "a": self.user_a,
                "b": self.user_b,
            }.get(request.headers.get("x-test-user"))

        app.dependency_overrides[get_current_user_optional] = current_user
        app.dependency_overrides[get_run_repository] = lambda: self.repository
        app.dependency_overrides[get_investigation_workflow] = lambda: self.workflow
        app.dependency_overrides[get_live_run_task_registry] = (
            lambda: _HoldingLiveRunTaskRegistry()
        )

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    @staticmethod
    def _request() -> dict[str, str]:
        return {
            "repository_owner": "octo-org",
            "repository_name": "analytics",
            "question": "Why did checkout failures increase?",
            "incident_reference": "incident:checkout-500",
        }

    def _create_as(self, user_header: str | None) -> UUID:
        headers = {"x-test-user": user_header} if user_header is not None else {}
        response = self.client.post("/v1/investigations", headers=headers, json=self._request())
        self.assertEqual(response.status_code, 202)
        return UUID(response.json()["run_id"])

    def test_owned_run_is_invisible_to_another_user_for_get_follow_up_and_sse(self) -> None:
        run_id = self._create_as("a")
        self.assertEqual(self.repository.history[-1].user_id, self.user_a.id)

        owner_response = self.client.get(f"/v1/runs/{run_id}", headers={"x-test-user": "a"})
        self.assertEqual(owner_response.status_code, 200)
        self.assertNotIn("user_id", owner_response.json())

        missing_id = uuid4()
        cross_user_get = self.client.get(
            f"/v1/runs/{run_id}", headers={"x-test-user": "b"}
        )
        missing_get = self.client.get(
            f"/v1/runs/{missing_id}", headers={"x-test-user": "b"}
        )
        self.assertEqual(cross_user_get.status_code, 404)
        self.assertEqual(cross_user_get.json(), missing_get.json())

        cross_user_follow_up = self.client.post(
            f"/v1/investigations/{run_id}/follow-up",
            headers={"x-test-user": "b"},
            json={"question": "Anything else?"},
        )
        missing_follow_up = self.client.post(
            f"/v1/investigations/{missing_id}/follow-up",
            headers={"x-test-user": "b"},
            json={"question": "Anything else?"},
        )
        self.assertEqual(cross_user_follow_up.status_code, 404)
        self.assertEqual(cross_user_follow_up.json(), missing_follow_up.json())

        cross_user_events = asyncio.run(
            stream_run_events(
                run_id,
                SimpleNamespace(),
                self.repository,
                self.user_b,
            )
        )
        missing_events = asyncio.run(
            stream_run_events(
                missing_id,
                SimpleNamespace(),
                self.repository,
                self.user_b,
            )
        )
        self.assertIsInstance(cross_user_events, JSONResponse)
        self.assertEqual(cross_user_events.status_code, 404)
        self.assertEqual(cross_user_events.body, missing_events.body)

    def test_anonymous_run_remains_visible_to_anonymous_and_authenticated_callers(self) -> None:
        run_id = self._create_as(None)
        self.assertIsNone(self.repository.history[-1].user_id)

        anonymous = self.client.get(f"/v1/runs/{run_id}")
        authenticated = self.client.get(
            f"/v1/runs/{run_id}", headers={"x-test-user": "a"}
        )
        self.assertEqual(anonymous.status_code, 200)
        self.assertEqual(authenticated.status_code, 200)
        self.assertIsNotNone(self.repository.get(run_id, None))
        self.assertIsNotNone(self.repository.get(run_id, self.user_a.id))


if __name__ == "__main__":
    unittest.main()
