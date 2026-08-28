import asyncio
import os
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

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
from app.investigations.hypotheses import (
    GroundedInvestigationResult,
    GroundedTerminationReason,
)
from app.investigations.models import InvestigationRequest
from app.policy import evaluate_merge_readiness
from app.runtime import (
    ExplanationSource,
    RunStateConflictError,
    RunStatus,
    create_pending_run,
    transition_run,
)
from app.runtime.investigation_models import (
    MAX_FOLLOW_UPS_PER_CASE,
    ExecutionState,
    InvestigationRun,
    InvestigationRuntimeSnapshot,
    WorkingMemory,
)
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

    def execute_workflow(
        self,
        github_connector=FakeGitHubConnector(),
        explanation_provider=ExplanationSource.FAKE,
    ):
        run = asyncio.run(
            MergeReadinessWorkflowService(
                github_connector,
                FakeJiraConnector(),
                self.repository,
                explanation_provider=explanation_provider,
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

    def test_groq_explanation_source_round_trips(self) -> None:
        created = self.execute_workflow(
            explanation_provider=ExplanationSource.GROQ
        )

        retrieved = self.repository.get(created.run_id)

        self.assertIs(retrieved.sources.explanation, ExplanationSource.GROQ)

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


@unittest.skipUnless(
    TEST_DATABASE_URL is not None,
    "TEST_DATABASE_URL is not configured; PostgreSQL persistence was not verified.",
)
class PostgresInvestigationReopenTests(unittest.TestCase):
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

    def _completed_investigation(self) -> InvestigationRun:
        now = datetime.now(UTC)
        request = InvestigationRequest(
            repository_owner="octo-org",
            repository_name="analytics",
            question="Why did checkout fail?",
            incident_reference="incident:checkout-500",
        )
        pending = InvestigationRun(
            run_id=uuid4(),
            workflow_name="investigation",
            workflow_version="1",
            status=RunStatus.PENDING,
            started_at=None,
            completed_at=None,
            error=None,
            request=request,
            state=None,
        )
        self.repository.save(pending)
        self.created_run_ids.append(pending.run_id)

        running = pending.model_copy(
            update={"status": RunStatus.RUNNING, "started_at": now}
        )
        self.repository.save(running)

        state = InvestigationRuntimeSnapshot(
            working_memory=WorkingMemory(),
            execution_state=ExecutionState(
                max_tool_calls=6, used_tool_calls=1, remaining_tool_calls=5
            ),
        )
        result = GroundedInvestigationResult(
            termination_reason=GroundedTerminationReason.COMPLETED,
            summary="Investigation complete.",
        )
        completed = running.model_copy(
            update={
                "status": RunStatus.COMPLETED,
                "completed_at": now,
                "state": state,
                "results": (result,),
            }
        )
        self.repository.save(completed)
        return completed

    def test_completed_investigation_can_reopen_to_running(self) -> None:
        completed = self._completed_investigation()

        reopened = completed.model_copy(
            update={
                "status": RunStatus.RUNNING,
                "completed_at": None,
                "follow_up_count": completed.follow_up_count + 1,
            }
        )
        self.repository.save(reopened)

        retrieved = self.repository.get(completed.run_id)
        self.assertEqual(retrieved.status, RunStatus.RUNNING)
        self.assertEqual(retrieved.follow_up_count, 1)
        self.assertEqual(retrieved.results, completed.results)

    def test_investigation_reopen_rejected_on_a_non_sequential_follow_up_count(
        self,
    ) -> None:
        completed = self._completed_investigation()
        self.assertEqual(completed.follow_up_count, 0)

        jumped = completed.model_copy(
            update={
                "status": RunStatus.RUNNING,
                "completed_at": None,


                "follow_up_count": 3,
            }
        )
        with self.assertRaises(RunStateConflictError) as raised:
            self.repository.save(jumped)

        self.assertIn("exactly one more", str(raised.exception))


        retrieved = self.repository.get(completed.run_id)
        self.assertEqual(retrieved.status, RunStatus.COMPLETED)
        self.assertEqual(retrieved.follow_up_count, 0)

    def test_investigation_reopen_rejected_once_follow_up_cap_reached(self) -> None:
        completed = self._completed_investigation()
        at_cap = self.repository.get(completed.run_id)


        with self.session_factory.begin() as session:
            session.execute(
                update(WorkflowRunRow)
                .where(WorkflowRunRow.run_id == completed.run_id)
                .values(follow_up_count=MAX_FOLLOW_UPS_PER_CASE)
            )

        reopened = at_cap.model_copy(
            update={
                "status": RunStatus.RUNNING,
                "completed_at": None,
                "follow_up_count": MAX_FOLLOW_UPS_PER_CASE + 1,
            }
        )
        with self.assertRaises(RunStateConflictError):
            self.repository.save(reopened)

    def test_merge_readiness_run_still_cannot_reopen_from_completed(self) -> None:
        github = asyncio.run(
            FakeGitHubConnector().get_pull_request(MERGE_READY_REQUEST)
        )
        jira = asyncio.run(FakeJiraConnector().get_issue(github.linked_jira_key))
        result = evaluate_merge_readiness(github, jira)
        now = datetime.now(UTC)

        pending = create_pending_run(MERGE_READY_REQUEST)
        self.repository.save(pending)
        self.created_run_ids.append(pending.run_id)

        running = transition_run(pending, RunStatus.RUNNING, now)
        self.repository.save(running)

        completed = transition_run(running, RunStatus.COMPLETED, now, result=result)
        self.repository.save(completed)

        reopened = completed.model_copy(
            update={"status": RunStatus.RUNNING, "completed_at": None}
        )
        with self.assertRaises(RunStateConflictError):
            self.repository.save(reopened)


if __name__ == "__main__":
    unittest.main()
