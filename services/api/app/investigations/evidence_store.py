import logging
from uuid import UUID

from app.investigations.models import Evidence
from app.observability.structured_logging import (
    NoOpStructuredEventLogger,
    StructuredEventLogger,
)


class EvidenceStore:
    def __init__(
        self,
        *,
        event_logger: StructuredEventLogger | NoOpStructuredEventLogger | None = None,
        run_id: UUID | None = None,
    ) -> None:
        self._evidence_by_id: dict[str, Evidence] = {}
        self._event_logger = event_logger or NoOpStructuredEventLogger()
        self._run_id = run_id

    def put(self, evidence: Evidence) -> str:
        existing = self._evidence_by_id.get(evidence.evidence_id)
        if existing is not None and existing.content != evidence.content:
            self._event_logger.emit(
                "evidence.conflicting_write_dropped",
                logging.WARNING,
                run_id=self._run_id,
                evidence_id=evidence.evidence_id,
            )
        self._evidence_by_id.setdefault(evidence.evidence_id, evidence)
        return evidence.evidence_id

    def get(self, evidence_id: str) -> Evidence:
        return self._evidence_by_id[evidence_id]

    def get_many(self, evidence_ids: tuple[str, ...]) -> tuple[Evidence, ...]:
        return tuple(self._evidence_by_id[evidence_id] for evidence_id in evidence_ids)
