import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from pydantic import ValidationError

from app.connectors.fakes import FakeGitHubConnector, FakeJiraConnector
from app.connectors.fixture_catalog import MERGE_READY_REQUEST
from app.policy import evaluate_merge_readiness
from app.runtime import (
    ExplanationSource,
    InvalidStateTransitionError,
    RunStatus,
    RunSources,
    RuntimeErrorCode,
    RuntimeErrorInfo,
    StepStatus,
    WorkflowStepName,
    create_pending_run,
    create_pending_step,
    transition_run,
    transition_step,
)


class RuntimeStateTests(unittest.TestCase):
    def test_unknown_source_values_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            RunSources(
                github="github-enterprise",
                jira="fake",
                explanation="fake",
            )

    def test_pending_run_keeps_bounded_source_provenance(self) -> None:
        run = create_pending_run(
            MERGE_READY_REQUEST,
            sources=RunSources(
                github="live",
                jira="fake",
                explanation=ExplanationSource.GEMINI,
            ),
        )

        self.assertEqual(run.sources.github.value, "live")
        self.assertEqual(run.sources.jira.value, "fake")
        self.assertEqual(run.sources.explanation.value, "gemini")

    def test_groq_is_a_bounded_explanation_source(self) -> None:
        sources = RunSources(
            github="fake",
            jira="fake",
            explanation="groq",
        )

        self.assertIs(sources.explanation, ExplanationSource.GROQ)

    def test_completed_and_failed_runs_cannot_return_to_running(self) -> None:
        started_at = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)
        completed_at = started_at + timedelta(seconds=1)
        github = asyncio.run(
            FakeGitHubConnector().get_pull_request(MERGE_READY_REQUEST)
        )
        jira = asyncio.run(
            FakeJiraConnector().get_issue(github.linked_jira_key)
        )
        result = evaluate_merge_readiness(github, jira)

        running = transition_run(
            create_pending_run(MERGE_READY_REQUEST),
            RunStatus.RUNNING,
            started_at,
        )
        completed = transition_run(
            running,
            RunStatus.COMPLETED,
            completed_at,
            result=result,
        )

        with self.assertRaises(InvalidStateTransitionError):
            transition_run(completed, RunStatus.RUNNING, completed_at)

        failed = transition_run(
            running,
            RunStatus.FAILED,
            completed_at,
            error=RuntimeErrorInfo(
                code=RuntimeErrorCode.POLICY_EXECUTION_FAILED,
                message="The policy step failed.",
            ),
        )

        with self.assertRaises(InvalidStateTransitionError):
            transition_run(failed, RunStatus.RUNNING, completed_at)

    def test_completed_step_cannot_return_to_running(self) -> None:
        started_at = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)
        completed_at = started_at + timedelta(milliseconds=5)
        running = transition_step(
            create_pending_step(WorkflowStepName.FETCH_GITHUB_FACTS),
            StepStatus.RUNNING,
            started_at,
        )
        completed = transition_step(
            running,
            StepStatus.COMPLETED,
            completed_at,
            duration_ms=5,
        )

        with self.assertRaises(InvalidStateTransitionError):
            transition_step(completed, StepStatus.RUNNING, completed_at)


if __name__ == "__main__":
    unittest.main()
