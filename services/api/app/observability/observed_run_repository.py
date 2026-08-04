pass

from uuid import UUID

from app.observability.contracts import (
    FailureCategory,
    PersistenceOperation,
    PersistenceOutcome,
    current_persistence_checkpoint,
)
from app.observability.runtime_telemetry import RuntimeTelemetry
from app.runtime.errors import RunRecordInvalidError, RunStateConflictError
from app.runtime.models import MergeReadinessRun
from app.runtime.repository import RunRepository


def persistence_failure_category(error: Exception) -> FailureCategory:
    if isinstance(error, RunStateConflictError):
        return FailureCategory.STATE_CONFLICT
    if isinstance(error, RunRecordInvalidError):
        return FailureCategory.RECORD_INVALID
    return FailureCategory.PERSISTENCE_UNAVAILABLE


class ObservedRunRepository:
    pass

    def __init__(
        self,
        inner: RunRepository,
        telemetry: RuntimeTelemetry,
    ) -> None:
        self._inner = inner
        self._telemetry = telemetry

    def save(self, run: MergeReadinessRun) -> None:
        checkpoint = current_persistence_checkpoint()
        with self._telemetry.observe_persistence(
            PersistenceOperation.SAVE,
            run.run_id,
            checkpoint,
        ) as observation:
            try:
                self._inner.save(run)
            except Exception as error:
                category = persistence_failure_category(error)
                observation.set_attributes(
                    **{
                        "promptql.persistence.outcome": (
                            PersistenceOutcome.FAILED.value
                        )
                    }
                )
                observation.mark_error(category)
                self._telemetry.record_persistence_failure(
                    PersistenceOperation.SAVE,
                    category,
                    run.run_id,
                    checkpoint,
                )
                raise
            observation.set_attributes(
                **{
                    "promptql.persistence.outcome": (
                        PersistenceOutcome.SUCCEEDED.value
                    )
                }
            )

    def get(self, run_id: UUID) -> MergeReadinessRun | None:
        with self._telemetry.observe_persistence(
            PersistenceOperation.GET,
            run_id,
            None,
        ) as observation:
            try:
                run = self._inner.get(run_id)
            except Exception as error:
                category = persistence_failure_category(error)
                observation.set_attributes(
                    **{
                        "promptql.persistence.outcome": (
                            PersistenceOutcome.FAILED.value
                        )
                    }
                )
                observation.mark_error(category)
                self._telemetry.record_persistence_failure(
                    PersistenceOperation.GET,
                    category,
                    run_id,
                    None,
                )
                raise

            outcome = (
                PersistenceOutcome.SUCCEEDED
                if run is not None
                else PersistenceOutcome.NOT_FOUND
            )
            observation.set_attributes(
                **{"promptql.persistence.outcome": outcome.value}
            )
            return run
