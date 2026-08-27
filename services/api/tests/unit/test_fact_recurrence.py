import unittest
from datetime import UTC, datetime
from uuid import uuid4

from app.explanations import FakeLLMClient
from app.investigations.models import InvestigationRequest
from app.runtime import (
    FACT_RECURRENCE_PROMOTION_THRESHOLD,
    InMemoryFactRecurrenceRepository,
    InMemoryRunRepository,
)
from app.workflows.investigation import InvestigationWorkflowService


class InMemoryFactRecurrenceRepositoryTests(unittest.TestCase):
    def test_two_occurrences_do_not_promote(self) -> None:
        repository = InMemoryFactRecurrenceRepository()
        for _ in range(2):
            repository.record_occurrence(
                "octo-org", "analytics", "changed_file", uuid4(), datetime.now(UTC)
            )

        record = repository.get("octo-org", "analytics", "changed_file")

        self.assertEqual(record.occurrence_count, 2)
        self.assertIsNone(record.promoted_at)

    def test_third_occurrence_promotes(self) -> None:
        self.assertEqual(FACT_RECURRENCE_PROMOTION_THRESHOLD, 3)
        repository = InMemoryFactRecurrenceRepository()
        for _ in range(FACT_RECURRENCE_PROMOTION_THRESHOLD - 1):
            repository.record_occurrence(
                "octo-org", "analytics", "changed_file", uuid4(), datetime.now(UTC)
            )
        self.assertIsNone(
            repository.get("octo-org", "analytics", "changed_file").promoted_at
        )

        promoting_run_id = uuid4()
        promoted_at = datetime.now(UTC)
        record = repository.record_occurrence(
            "octo-org", "analytics", "changed_file", promoting_run_id, promoted_at
        )

        self.assertEqual(record.occurrence_count, FACT_RECURRENCE_PROMOTION_THRESHOLD)
        self.assertEqual(record.promoted_at, promoted_at)
        self.assertEqual(record.last_observed_run_id, promoting_run_id)

    def test_promotion_is_never_cleared_by_later_occurrences(self) -> None:
        repository = InMemoryFactRecurrenceRepository()
        for _ in range(FACT_RECURRENCE_PROMOTION_THRESHOLD):
            repository.record_occurrence(
                "octo-org", "analytics", "changed_file", uuid4(), datetime.now(UTC)
            )
        first_promoted_at = repository.get(
            "octo-org", "analytics", "changed_file"
        ).promoted_at
        self.assertIsNotNone(first_promoted_at)

        record = repository.record_occurrence(
            "octo-org", "analytics", "changed_file", uuid4(), datetime.now(UTC)
        )

        self.assertEqual(record.occurrence_count, FACT_RECURRENCE_PROMOTION_THRESHOLD + 1)
        self.assertEqual(record.promoted_at, first_promoted_at)

    def test_a_different_repository_counter_is_unaffected(self) -> None:
        repository = InMemoryFactRecurrenceRepository()
        for _ in range(FACT_RECURRENCE_PROMOTION_THRESHOLD):
            repository.record_occurrence(
                "octo-org", "analytics", "changed_file", uuid4(), datetime.now(UTC)
            )

        other_repository_record = repository.get(
            "other-org", "other-repo", "changed_file"
        )

        self.assertIsNone(other_repository_record)


        record = repository.record_occurrence(
            "other-org", "other-repo", "changed_file", uuid4(), datetime.now(UTC)
        )
        self.assertEqual(record.occurrence_count, 1)
        self.assertIsNone(record.promoted_at)
        self.assertEqual(
            repository.get("octo-org", "analytics", "changed_file").occurrence_count,
            FACT_RECURRENCE_PROMOTION_THRESHOLD,
        )

    def test_a_fact_type_that_never_recurs_stays_at_one(self) -> None:
        repository = InMemoryFactRecurrenceRepository()

        record = repository.record_occurrence(
            "octo-org", "analytics", "deployment_preceded_incident", uuid4(), datetime.now(UTC)
        )

        self.assertEqual(record.occurrence_count, 1)
        self.assertIsNone(record.promoted_at)
        self.assertEqual(
            repository.get(
                "octo-org", "analytics", "deployment_preceded_incident"
            ).occurrence_count,
            1,
        )


def _fake_request(repository_owner: str, repository_name: str) -> InvestigationRequest:
    return InvestigationRequest(
        repository_owner=repository_owner,
        repository_name=repository_name,
        question="Why did checkout fail?",
        incident_reference="incident:checkout-500",
        pull_request_number=42,
    )


class InvestigationWorkflowFactRecurrenceTests(unittest.IsolatedAsyncioTestCase):
    async def _run_once(self, fact_recurrence_repository, repository_owner="octo-org", repository_name="analytics"):
        workflow = InvestigationWorkflowService(
            InMemoryRunRepository(),
            FakeLLMClient(),
            fact_recurrence_repository=fact_recurrence_repository,
        )
        pending = await workflow.create_persisted_run(
            _fake_request(repository_owner, repository_name)
        )
        return await workflow.continue_persisted_run(pending)

    async def test_third_completed_run_promotes_its_recurring_fact_types(self) -> None:
        fact_recurrence_repository = InMemoryFactRecurrenceRepository()

        for _ in range(FACT_RECURRENCE_PROMOTION_THRESHOLD - 1):
            completed = await self._run_once(fact_recurrence_repository)
            self.assertEqual(completed.status.value, "completed")
            self.assertIsNone(
                fact_recurrence_repository.get(
                    "octo-org", "analytics", "changed_file"
                ).promoted_at
            )

        completed = await self._run_once(fact_recurrence_repository)

        self.assertEqual(completed.status.value, "completed")
        changed_file_record = fact_recurrence_repository.get(
            "octo-org", "analytics", "changed_file"
        )
        self.assertEqual(
            changed_file_record.occurrence_count, FACT_RECURRENCE_PROMOTION_THRESHOLD
        )
        self.assertIsNotNone(changed_file_record.promoted_at)
        self.assertEqual(changed_file_record.last_observed_run_id, completed.run_id)

        match_record = fact_recurrence_repository.get(
            "octo-org", "analytics", "changed_file_matches_failure_file"
        )
        self.assertEqual(
            match_record.occurrence_count, FACT_RECURRENCE_PROMOTION_THRESHOLD
        )
        self.assertIsNotNone(match_record.promoted_at)

    async def test_a_different_repository_is_not_promoted_by_another_repositorys_runs(
        self,
    ) -> None:
        fact_recurrence_repository = InMemoryFactRecurrenceRepository()

        for _ in range(FACT_RECURRENCE_PROMOTION_THRESHOLD):
            await self._run_once(fact_recurrence_repository)
        fact_recurrence_repository.record_occurrence(
            "other-org", "other-repo", "changed_file", uuid4(), datetime.now(UTC)
        )

        other_record = fact_recurrence_repository.get(
            "other-org", "other-repo", "changed_file"
        )
        self.assertEqual(other_record.occurrence_count, 1)
        self.assertIsNone(other_record.promoted_at)
        self.assertEqual(
            fact_recurrence_repository.get(
                "octo-org", "analytics", "changed_file"
            ).occurrence_count,
            FACT_RECURRENCE_PROMOTION_THRESHOLD,
        )


if __name__ == "__main__":
    unittest.main()
