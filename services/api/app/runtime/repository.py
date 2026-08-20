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
