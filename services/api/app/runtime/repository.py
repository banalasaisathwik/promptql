from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol
from uuid import UUID

from typing import TYPE_CHECKING

from app.runtime.models import MergeReadinessRun

if TYPE_CHECKING:
    from app.runtime.investigation_models import InvestigationRun


RuntimeRun = MergeReadinessRun


class RunRepository(Protocol):
    def save(self, run: RuntimeRun) -> None: ...

    def get(self, run_id: UUID) -> RuntimeRun | None: ...


class InMemoryRunRepository:
    def __init__(self) -> None:
        self._runs: dict[UUID, RuntimeRun] = {}
        self._history: list[RuntimeRun] = []


    def save(self, run: RuntimeRun) -> None:
        self._runs[run.run_id] = run
        self._history.append(run)

    def get(self, run_id: UUID) -> RuntimeRun | None:
        return self._runs.get(run_id)

    @property
    def history(self) -> tuple[RuntimeRun, ...]:
        return tuple(self._history)


FACT_RECURRENCE_PROMOTION_THRESHOLD = 3


@dataclass(frozen=True)
class FactRecurrenceRecord:
    repository_owner: str
    repository_name: str
    fact_type: str
    occurrence_count: int
    first_observed_run_id: UUID
    last_observed_run_id: UUID
    last_observed_at: datetime
    promoted_at: datetime | None


class FactRecurrenceRepository(Protocol):
    def record_occurrence(
        self,
        repository_owner: str,
        repository_name: str,
        fact_type: str,
        run_id: UUID,
        observed_at: datetime,
    ) -> FactRecurrenceRecord: ...


class InMemoryFactRecurrenceRepository:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str, str], FactRecurrenceRecord] = {}

    def record_occurrence(
        self,
        repository_owner: str,
        repository_name: str,
        fact_type: str,
        run_id: UUID,
        observed_at: datetime,
    ) -> FactRecurrenceRecord:
        key = (repository_owner, repository_name, fact_type)
        existing = self._records.get(key)
        if existing is None:
            record = FactRecurrenceRecord(
                repository_owner=repository_owner,
                repository_name=repository_name,
                fact_type=fact_type,
                occurrence_count=1,
                first_observed_run_id=run_id,
                last_observed_run_id=run_id,
                last_observed_at=observed_at,
                promoted_at=None,
            )
        else:
            occurrence_count = existing.occurrence_count + 1
            promoted_at = existing.promoted_at
            if promoted_at is None and occurrence_count >= FACT_RECURRENCE_PROMOTION_THRESHOLD:
                promoted_at = observed_at
            record = replace(
                existing,
                occurrence_count=occurrence_count,
                last_observed_run_id=run_id,
                last_observed_at=observed_at,
                promoted_at=promoted_at,
            )
        self._records[key] = record
        return record

    def get(
        self, repository_owner: str, repository_name: str, fact_type: str
    ) -> FactRecurrenceRecord | None:
        return self._records.get((repository_owner, repository_name, fact_type))
