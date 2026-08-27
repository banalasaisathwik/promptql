from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, case
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import RepositoryFactRecurrenceRow
from app.runtime import (
    FACT_RECURRENCE_PROMOTION_THRESHOLD,
    FactRecurrenceRecord,
    RunPersistenceError,
)


def _read_record(stored_row: RepositoryFactRecurrenceRow) -> FactRecurrenceRecord:
    return FactRecurrenceRecord(
        repository_owner=stored_row.repository_owner,
        repository_name=stored_row.repository_name,
        fact_type=stored_row.fact_type,
        occurrence_count=stored_row.occurrence_count,
        first_observed_run_id=stored_row.first_observed_run_id,
        last_observed_run_id=stored_row.last_observed_run_id,
        last_observed_at=stored_row.last_observed_at,
        promoted_at=stored_row.promoted_at,
    )


class PostgresFactRecurrenceRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record_occurrence(
        self,
        repository_owner: str,
        repository_name: str,
        fact_type: str,
        run_id: UUID,
        observed_at: datetime,
    ) -> FactRecurrenceRecord:
        insert_statement = insert(RepositoryFactRecurrenceRow).values(
            repository_owner=repository_owner,
            repository_name=repository_name,
            fact_type=fact_type,
            occurrence_count=1,
            first_observed_run_id=run_id,
            last_observed_run_id=run_id,
            last_observed_at=observed_at,
            promoted_at=None,
        )
        incremented_count = RepositoryFactRecurrenceRow.occurrence_count + 1
        upsert_statement = insert_statement.on_conflict_do_update(
            index_elements=["repository_owner", "repository_name", "fact_type"],
            set_={
                "occurrence_count": incremented_count,
                "last_observed_run_id": run_id,
                "last_observed_at": observed_at,
                "promoted_at": case(
                    (
                        and_(
                            RepositoryFactRecurrenceRow.promoted_at.is_(None),
                            incremented_count >= FACT_RECURRENCE_PROMOTION_THRESHOLD,
                        ),
                        observed_at,
                    ),
                    else_=RepositoryFactRecurrenceRow.promoted_at,
                ),
            },
        ).returning(RepositoryFactRecurrenceRow)

        try:
            with self._session_factory.begin() as session:
                stored_row = session.execute(upsert_statement).scalars().one()
        except SQLAlchemyError:
            raise RunPersistenceError(
                "Runtime persistence is unavailable.", run_id
            ) from None
        return _read_record(stored_row)
