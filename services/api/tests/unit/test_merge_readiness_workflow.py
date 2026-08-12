import unittest

from app.connectors.fakes import FakeGitHubConnector, FakeJiraConnector
from app.connectors.fixture_catalog import FAILED_CI_REQUEST, MERGE_READY_REQUEST
from app.connectors.models import ConnectorRequest, ConnectorSource, GitHubPullRequest
from app.policy.models import MergeReadinessDecision, MergeReadinessResult
from app.runtime import (
    InMemoryRunRepository,
    RunStatus,
    RuntimeErrorCode,
    StepStatus,
    WorkflowStepName,
)
from app.workflows import MergeReadinessWorkflowService


class FailingGitHubConnector:
    source = ConnectorSource.FAKE

    async def get_pull_request(
        self,
        _request: ConnectorRequest,
    ) -> GitHubPullRequest:
        raise RuntimeError("secret-token-must-not-leak")


class LiveFactsGitHubConnector(FakeGitHubConnector):
    source = ConnectorSource.LIVE


class LiveFactsJiraConnector(FakeJiraConnector):
    source = ConnectorSource.LIVE


def failing_policy(_github, _jira) -> MergeReadinessResult:
    raise RuntimeError("private-policy-detail")


def create_workflow(
    repository: InMemoryRunRepository,
    *,
    github_connector=FakeGitHubConnector(),
    policy_evaluator=None,
) -> MergeReadinessWorkflowService:
    arguments = {
        "github_connector": github_connector,
        "jira_connector": FakeJiraConnector(),
        "run_repository": repository,
    }
    if policy_evaluator is not None:
        arguments["policy_evaluator"] = policy_evaluator
    return MergeReadinessWorkflowService(**arguments)


class MergeReadinessWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_connector_sources_are_preserved_in_the_run(self) -> None:
        run = await MergeReadinessWorkflowService(
            LiveFactsGitHubConnector(),
            LiveFactsJiraConnector(),
            InMemoryRunRepository(),
        ).execute(MERGE_READY_REQUEST)

        self.assertEqual(run.sources.github, ConnectorSource.LIVE)
        self.assertEqual(run.sources.jira, ConnectorSource.LIVE)

    async def test_successful_ready_workflow_completes(self) -> None:
        repository = InMemoryRunRepository()

        run = await create_workflow(repository).execute(MERGE_READY_REQUEST)

        self.assertEqual(run.status, RunStatus.COMPLETED)
        self.assertEqual(run.result.decision, MergeReadinessDecision.READY)
        self.assertIsNone(run.error)
        self.assertIsNotNone(run.started_at)
        self.assertIsNotNone(run.completed_at)
        self.assertTrue(all(step.duration_ms is not None for step in run.steps))
        self.assertEqual(repository.get(run.run_id), run)

    async def test_failed_ci_is_completed_blocked_not_runtime_failed(self) -> None:
        run = await create_workflow(InMemoryRunRepository()).execute(
            FAILED_CI_REQUEST
        )

        self.assertEqual(run.status, RunStatus.COMPLETED)
        self.assertEqual(run.result.decision, MergeReadinessDecision.BLOCKED)
        self.assertIsNone(run.error)
        self.assertTrue(
            all(step.status is StepStatus.COMPLETED for step in run.steps)
        )

    async def test_connector_exception_marks_step_and_run_failed(self) -> None:
        run = await create_workflow(
            InMemoryRunRepository(),
            github_connector=FailingGitHubConnector(),
        ).execute(MERGE_READY_REQUEST)

        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertIsNone(run.result)
        self.assertEqual(len(run.steps), 1)
        self.assertEqual(run.steps[0].status, StepStatus.FAILED)
        self.assertEqual(
            run.error.code,
            RuntimeErrorCode.CONNECTOR_EXECUTION_FAILED,
        )
        self.assertNotIn("secret-token", run.error.message)

    async def test_policy_exception_marks_policy_step_and_run_failed(self) -> None:
        repository = InMemoryRunRepository()
        run = await create_workflow(
            repository,
            policy_evaluator=failing_policy,
        ).execute(MERGE_READY_REQUEST)

        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertIsNone(run.result)
        self.assertEqual(len(run.steps), 3)
        self.assertEqual(run.steps[-1].status, StepStatus.FAILED)
        self.assertEqual(
            run.error.code,
            RuntimeErrorCode.POLICY_EXECUTION_FAILED,
        )
        self.assertNotIn("private-policy-detail", run.error.message)
        self.assertFalse(
            any(
                snapshot.status is RunStatus.RUNNING
                and snapshot.steps
                and snapshot.steps[-1].status is StepStatus.FAILED
                for snapshot in repository.history
            )
        )

    async def test_policy_step_and_completed_run_share_one_saved_checkpoint(self) -> None:
        repository = InMemoryRunRepository()

        run = await create_workflow(repository).execute(MERGE_READY_REQUEST)

        self.assertEqual(run.status, RunStatus.COMPLETED)
        self.assertFalse(
            any(
                snapshot.status is RunStatus.RUNNING
                and snapshot.steps
                and snapshot.steps[-1].name
                is WorkflowStepName.EVALUATE_MERGE_READINESS
                and snapshot.steps[-1].status is StepStatus.COMPLETED
                for snapshot in repository.history
            )
        )

    async def test_steps_are_recorded_in_execution_order(self) -> None:
        run = await create_workflow(InMemoryRunRepository()).execute(
            MERGE_READY_REQUEST
        )

        self.assertEqual(
            tuple(step.name for step in run.steps),
            (
                WorkflowStepName.FETCH_GITHUB_FACTS,
                WorkflowStepName.FETCH_JIRA_FACTS,
                WorkflowStepName.EVALUATE_MERGE_READINESS,
            ),
        )
        self.assertTrue(all(step.attempt == 1 for step in run.steps))

    async def test_every_execution_has_a_unique_run_id_and_same_policy_result(self) -> None:
        workflow = create_workflow(InMemoryRunRepository())

        first = await workflow.execute(MERGE_READY_REQUEST)
        second = await workflow.execute(MERGE_READY_REQUEST)

        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual(first.result, second.result)


if __name__ == "__main__":
    unittest.main()
