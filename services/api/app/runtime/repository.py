pass

from typing import Protocol
from uuid import UUID

from app.runtime.models import MergeReadinessRun


class RunRepository(Protocol):
    pass

    def save(self, run: MergeReadinessRun) -> None: ...

    def get(self, run_id: UUID) -> MergeReadinessRun | None: ...


class InMemoryRunRepository:
    pass

    def __init__(self) -> None:
        self._runs: dict[UUID, MergeReadinessRun] = {}
        self._history: list[MergeReadinessRun] = []

    def save(self, run: MergeReadinessRun) -> None:
        self._runs[run.run_id] = run
        self._history.append(run)

    def get(self, run_id: UUID) -> MergeReadinessRun | None:
        return self._runs.get(run_id)

    @property
    def history(self) -> tuple[MergeReadinessRun, ...]:
        pass

        return tuple(self._history)
