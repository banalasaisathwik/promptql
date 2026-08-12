import asyncio
import os
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import delete, inspect, update

from app.config import DatabaseSettings
from app.connectors.fakes import FakeGitHubConnector, FakeJiraConnector
from app.connectors.fixture_catalog import MERGE_READY_REQUEST
from app.connectors.models import ConnectorRequest, ConnectorSource, GitHubPullRequest
from app.database import (
    PostgresRunRepository,
    create_database_engine,
    create_session_factory,
)
from app.database.models import WorkflowRunRow
from app.runtime import RunStateConflictError, create_pending_run
from app.workflows import MergeReadinessWorkflowService
from tests.postgres_support import load_safe_test_database_url


TEST_DATABASE_URL = load_safe_test_database_url()


class FailingGitHubConnector:
    source = ConnectorSource.LIVE

    async def get_pull_request(
        self,
        _request: ConnectorRequest,
    ) -> GitHubPullRequest:
        raise RuntimeError("database-test-secret-must-not-leak")


@unittest.skipUnless(
    TEST_DATABASE_URL is not None,
    "TEST_DATABASE_URL is not configured; PostgreSQL persistence was not verified.",
)
class PostgresRuntimePersistenceTests(unittest.TestCase):
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

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.created_run_ids = []
        self.repository = PostgresRunRepository(self.session_factory)

    def tearDown(self) -> None:
        if not self.created_run_ids:
            return
        with self.session_factory.begin() as session:
            session.execute(
                delete(WorkflowRunRow).where(
                    WorkflowRunRow.run_id.in_(self.created_run_ids)
                )
            )

    def execute_workflow(self, github_connector=FakeGitHubConnector()):
        run = asyncio.run(
            MergeReadinessWorkflowService(
                github_connector,
                FakeJiraConnector(),
                self.repository,
            ).execute(MERGE_READY_REQUEST)
        )
        self.created_run_ids.append(run.run_id)
        return run

    def test_migration_creates_only_required_runtime_tables(self) -> None:
        table_names = set(inspect(self.engine).get_table_names())

        self.assertIn("workflow_runs", table_names)
        self.assertIn("workflow_steps", table_names)

    def test_completed_run_round_trips_with_ordered_steps(self) -> None:
        created = self.execute_workflow()

        retrieved = self.repository.get(created.run_id)

        self.assertEqual(retrieved, created)
        self.assertEqual(
            [step.name for step in retrieved.steps],
            [step.name for step in created.steps],
        )
        self.assertEqual(retrieved.sources.github.value, "fake")
        self.assertEqual(retrieved.sources.jira.value, "fake")
        self.assertEqual(retrieved.sources.explanation.value, "fake")

    def test_pre_provenance_run_remains_readable(self) -> None:
        created = self.execute_workflow()
        with self.session_factory.begin() as session:
            session.execute(
                update(WorkflowRunRow)
                .where(WorkflowRunRow.run_id == created.run_id)
                .values(
                    github_source=None,
                    jira_source=None,
                    explanation_source=None,
                )
            )

        retrieved = self.repository.get(created.run_id)

        self.assertIsNotNone(retrieved)
        self.assertIsNone(retrieved.sources)

    def test_failed_run_and_sanitized_error_are_durable(self) -> None:
        created = self.execute_workflow(FailingGitHubConnector())

        retrieved = self.repository.get(created.run_id)

        self.assertEqual(retrieved, created)
        self.assertIsNone(retrieved.result)
        self.assertNotIn("database-test-secret", retrieved.error.message)

    def test_terminal_run_rejects_a_new_pending_snapshot(self) -> None:
        completed = self.execute_workflow()
        replacement = create_pending_run(
            MERGE_READY_REQUEST,
            run_id=completed.run_id,
        )

        with self.assertRaises(RunStateConflictError):
            self.repository.save(replacement)


if __name__ == "__main__":
    unittest.main()
