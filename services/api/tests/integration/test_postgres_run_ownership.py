import asyncio
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient
from sqlalchemy import delete, inspect

from app.api.v1.auth_router import SESSION_COOKIE_NAME
from app.api.v1.connector_router import (
    get_investigation_workflow,
    get_live_run_task_registry,
    get_run_repository,
)
from app.api.v1.live_events_router import stream_run_events
from app.auth import SessionSigner
from app.config import DatabaseSettings
from app.database import (
    PostgresRunRepository,
    PostgresUserRepository,
    create_database_engine,
    create_session_factory,
)
from app.database.models import UserRow, WorkflowRunRow
from app.explanations import FakeLLMClient
from app.investigations.models import InvestigationRequest
from app.main import app
from app.workflows import InvestigationWorkflowService
from tests.postgres_support import load_safe_test_database_url


TEST_DATABASE_URL = load_safe_test_database_url()


class _HoldingLiveRunTaskRegistry:
    def start(self, coroutine: object) -> None:
        coroutine.close()


@unittest.skipUnless(
    TEST_DATABASE_URL is not None,
    "TEST_DATABASE_URL is not configured; PostgreSQL ownership isolation was not verified.",
)
class PostgresRunOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert TEST_DATABASE_URL is not None
        api_root = Path(__file__).resolve().parents[2]
        alembic_config = Config(str(api_root / "alembic.ini"))
        previous_migration_url = os.environ.get("DATABASE_MIGRATION_URL")
        os.environ["DATABASE_MIGRATION_URL"] = TEST_DATABASE_URL.render_as_string(
            hide_password=False
        )
        try:
            command.upgrade(alembic_config, "head")
        finally:
            if previous_migration_url is None:
                os.environ.pop("DATABASE_MIGRATION_URL", None)
            else:
                os.environ["DATABASE_MIGRATION_URL"] = previous_migration_url

        cls.engine = create_database_engine(DatabaseSettings(TEST_DATABASE_URL))
        cls.session_factory = create_session_factory(cls.engine)
        cls.client = TestClient(app, client=("postgres-run-ownership", 50000))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        cls.engine.dispose()

    def setUp(self) -> None:
        self.created_run_ids: list[UUID] = []
        self.repository = PostgresRunRepository(self.session_factory)
        self.user_repository = PostgresUserRepository(self.session_factory)
        suffix = uuid4().hex
        self.user_a = self.user_repository.create_user(
            f"owner-{suffix}@example.com", "correct horse battery staple"
        )
        self.user_b = self.user_repository.create_user(
            f"other-{suffix}@example.com", "correct horse battery staple"
        )
        self.signer = SessionSigner("test-only-session-secret-key-32-chars", 3600)
        app.state.run_session_factory = self.session_factory
        app.state.session_signer = self.signer
        workflow = InvestigationWorkflowService(self.repository, FakeLLMClient())
        app.dependency_overrides[get_run_repository] = lambda: self.repository
        app.dependency_overrides[get_investigation_workflow] = lambda: workflow
        app.dependency_overrides[get_live_run_task_registry] = (
            lambda: _HoldingLiveRunTaskRegistry()
        )

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.state.run_session_factory = None
        app.state.session_signer = None
        with self.session_factory.begin() as session:
            if self.created_run_ids:
                session.execute(
                    delete(WorkflowRunRow).where(
                        WorkflowRunRow.run_id.in_(self.created_run_ids)
                    )
                )
            session.execute(
                delete(UserRow).where(UserRow.id.in_((self.user_a.id, self.user_b.id)))
            )

    @staticmethod
    def _request() -> dict[str, str]:
        return {
            "repository_owner": "octo-org",
            "repository_name": "analytics",
            "question": "Why did checkout failures increase?",
            "incident_reference": "incident:checkout-500",
        }

    def _headers_for(self, user_id: UUID) -> dict[str, str]:
        return {"cookie": f"{SESSION_COOKIE_NAME}={self.signer.sign(user_id)}"}

    def test_live_postgres_two_user_ownership_proof(self) -> None:
        created = self.client.post(
            "/v1/investigations",
            headers=self._headers_for(self.user_a.id),
            json=self._request(),
        )
        self.assertEqual(created.status_code, 202)
        run_id = UUID(created.json()["run_id"])
        self.created_run_ids.append(run_id)


        self.assertEqual(self.repository.get(run_id, self.user_a.id).user_id, self.user_a.id)
        self.assertIsNone(self.repository.get(run_id, self.user_b.id))

        owner_get = self.client.get(
            f"/v1/runs/{run_id}", headers=self._headers_for(self.user_a.id)
        )
        self.assertEqual(owner_get.status_code, 200)

        missing_id = uuid4()
        cross_user_get = self.client.get(
            f"/v1/runs/{run_id}", headers=self._headers_for(self.user_b.id)
        )
        missing_get = self.client.get(
            f"/v1/runs/{missing_id}", headers=self._headers_for(self.user_b.id)
        )
        self.assertEqual(cross_user_get.status_code, 404)
        self.assertEqual(cross_user_get.json(), missing_get.json())

        cross_user_follow_up = self.client.post(
            f"/v1/investigations/{run_id}/follow-up",
            headers=self._headers_for(self.user_b.id),
            json={"question": "Anything else?"},
        )
        missing_follow_up = self.client.post(
            f"/v1/investigations/{missing_id}/follow-up",
            headers=self._headers_for(self.user_b.id),
            json={"question": "Anything else?"},
        )
        self.assertEqual(cross_user_follow_up.status_code, 404)
        self.assertEqual(cross_user_follow_up.json(), missing_follow_up.json())

        cross_user_events = asyncio.run(
            stream_run_events(run_id, SimpleNamespace(), self.repository, self.user_b)
        )
        missing_events = asyncio.run(
            stream_run_events(missing_id, SimpleNamespace(), self.repository, self.user_b)
        )
        self.assertIsInstance(cross_user_events, JSONResponse)
        self.assertEqual(cross_user_events.status_code, 404)
        self.assertEqual(cross_user_events.body, missing_events.body)

        owner_events = asyncio.run(
            stream_run_events(run_id, SimpleNamespace(app=app), self.repository, self.user_a)
        )
        self.assertIsInstance(owner_events, StreamingResponse)
        asyncio.run(owner_events.body_iterator.aclose())

        owner_still_visible = self.client.get(
            f"/v1/runs/{run_id}", headers=self._headers_for(self.user_a.id)
        )
        self.assertEqual(owner_still_visible.status_code, 200)

    def test_migration_has_nullable_owned_run_column_and_lookup_index(self) -> None:
        columns = {
            column["name"]: column for column in inspect(self.engine).get_columns("workflow_runs")
        }
        self.assertIn("user_id", columns)
        self.assertTrue(columns["user_id"]["nullable"])
        self.assertIn(
            "ix_workflow_runs_user_id",
            {index["name"] for index in inspect(self.engine).get_indexes("workflow_runs")},
        )


if __name__ == "__main__":
    unittest.main()
