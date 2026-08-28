import unittest
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError

from app.investigations.hypotheses import (
    GroundedInvestigationResult,
    GroundedTerminationReason,
)
from app.investigations.models import InvestigationRequest
from app.runtime.investigation_models import (
    MAX_FOLLOW_UPS_PER_CASE,
    ExecutionState,
    InvestigationRun,
    InvestigationRuntimeSnapshot,
    WorkingMemory,
)
from app.runtime.models import RunStatus


def _request() -> InvestigationRequest:
    return InvestigationRequest(
        repository_owner="octo-org",
        repository_name="analytics",
        question="Why did checkout fail?",
        incident_reference="incident:checkout-500",
    )


def _state() -> InvestigationRuntimeSnapshot:
    return InvestigationRuntimeSnapshot(
        working_memory=WorkingMemory(),
        execution_state=ExecutionState(
            max_tool_calls=6, used_tool_calls=1, remaining_tool_calls=5
        ),
    )


def _result() -> GroundedInvestigationResult:
    return GroundedInvestigationResult(
        termination_reason=GroundedTerminationReason.COMPLETED,
        summary="Investigation complete.",
    )


def _base_kwargs() -> dict:
    return {
        "run_id": uuid4(),
        "workflow_name": "investigation",
        "workflow_version": "1",
        "error": None,
        "request": _request(),
    }


class InvestigationRunLifecycleTests(unittest.TestCase):
    def test_pending_investigation_requires_empty_results_and_zero_follow_ups(self) -> None:
        pending = InvestigationRun(
            **_base_kwargs(),
            status=RunStatus.PENDING,
            started_at=None,
            completed_at=None,
            state=None,
        )

        self.assertEqual(pending.results, ())
        self.assertEqual(pending.follow_up_count, 0)

    def test_pending_investigation_rejects_a_nonzero_follow_up_count(self) -> None:
        with self.assertRaises(ValidationError):
            InvestigationRun(
                **_base_kwargs(),
                status=RunStatus.PENDING,
                started_at=None,
                completed_at=None,
                state=None,
                follow_up_count=1,
            )

    def test_completed_investigation_requires_at_least_one_result(self) -> None:
        now = datetime.now(UTC)
        with self.assertRaises(ValidationError):
            InvestigationRun(
                **_base_kwargs(),
                status=RunStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                state=_state(),
                results=(),
            )

    def test_completed_investigation_accepts_one_result(self) -> None:
        now = datetime.now(UTC)
        completed = InvestigationRun(
            **_base_kwargs(),
            status=RunStatus.COMPLETED,
            started_at=now,
            completed_at=now,
            state=_state(),
            results=(_result(),),
        )

        self.assertEqual(len(completed.results), 1)

    def test_running_investigation_may_carry_forward_prior_results(self) -> None:
        now = datetime.now(UTC)
        reopened = InvestigationRun(
            **_base_kwargs(),
            status=RunStatus.RUNNING,
            started_at=now,
            completed_at=None,
            state=_state(),
            results=(_result(),),
            follow_up_count=1,
        )

        self.assertEqual(len(reopened.results), 1)
        self.assertEqual(reopened.follow_up_count, 1)

    def test_follow_up_count_cannot_go_negative(self) -> None:
        now = datetime.now(UTC)
        with self.assertRaises(ValidationError):
            InvestigationRun(
                **_base_kwargs(),
                status=RunStatus.RUNNING,
                started_at=now,
                completed_at=None,
                state=None,
                follow_up_count=-1,
            )

    def test_max_follow_ups_per_case_is_not_enforced_by_the_model(self) -> None:
        now = datetime.now(UTC)
        over_cap = InvestigationRun(
            **_base_kwargs(),
            status=RunStatus.RUNNING,
            started_at=now,
            completed_at=None,
            state=_state(),
            results=(_result(),),
            follow_up_count=MAX_FOLLOW_UPS_PER_CASE + 1,
        )

        self.assertEqual(over_cap.follow_up_count, MAX_FOLLOW_UPS_PER_CASE + 1)

    def test_failed_investigation_may_retain_results_from_earlier_completed_rounds(
        self,
    ) -> None:
        now = datetime.now(UTC)
        failed = InvestigationRun(
            **_base_kwargs(),
            status=RunStatus.FAILED,
            started_at=now,
            completed_at=now,
            state=None,
            results=(_result(),),
            follow_up_count=1,
        )

        self.assertEqual(len(failed.results), 1)

    def test_failed_first_attempt_has_no_results(self) -> None:
        now = datetime.now(UTC)
        failed = InvestigationRun(
            **_base_kwargs(),
            status=RunStatus.FAILED,
            started_at=now,
            completed_at=now,
            state=None,
        )

        self.assertEqual(failed.results, ())


if __name__ == "__main__":
    unittest.main()
