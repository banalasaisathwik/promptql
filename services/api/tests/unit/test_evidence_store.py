import logging
import unittest
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.investigations.evidence_store import EvidenceStore
from app.investigations.models import (
    ChangedFileEvidenceContent,
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
    EvidenceSource,
    FileChangeType,
)


RUN_ID = UUID("33333333-3333-3333-3333-333333333333")
RETRIEVED_AT = datetime(2026, 8, 17, 10, 18, tzinfo=UTC)


class _RecordingEventLogger:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def emit(self, event: str, level: int = logging.INFO, **fields: Any) -> None:
        self.calls.append({"event": event, "level": level, **fields})


def _changed_file_evidence(
    *, evidence_id: str = "evidence:changed-file", path: str = "services/checkout.py"
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        source=EvidenceSource.GITHUB,
        kind=EvidenceKind.CHANGED_FILE,
        provenance=EvidenceProvenance(
            source_reference="github:acme/checkout:pr:42:file:services/checkout.py",
            retrieved_at=RETRIEVED_AT,
        ),
        content=ChangedFileEvidenceContent(
            repository_owner="acme",
            repository_name="checkout",
            pull_request_number=42,
            path=path,
            change_type=FileChangeType.MODIFIED,
            additions=4,
            deletions=2,
            changes=6,
            patch_available=True,
        ),
    )


class EvidenceStoreConflictTests(unittest.TestCase):
    def test_second_put_with_identical_content_keeps_first_and_emits_nothing(self) -> None:
        event_logger = _RecordingEventLogger()
        store = EvidenceStore(event_logger=event_logger, run_id=RUN_ID)
        first = _changed_file_evidence()
        second = _changed_file_evidence()

        store.put(first)
        store.put(second)

        self.assertIs(store.get(first.evidence_id), first)
        self.assertEqual(event_logger.calls, [])

    def test_second_put_with_different_content_keeps_first_and_emits_conflict_event(self) -> None:
        event_logger = _RecordingEventLogger()
        store = EvidenceStore(event_logger=event_logger, run_id=RUN_ID)
        first = _changed_file_evidence(path="services/checkout.py")
        second = _changed_file_evidence(path="services/checkout_v2.py")

        store.put(first)
        store.put(second)

        self.assertIs(store.get(first.evidence_id), first)
        self.assertEqual(len(event_logger.calls), 1)
        emitted = event_logger.calls[0]
        self.assertEqual(emitted["event"], "evidence.conflicting_write_dropped")
        self.assertEqual(emitted["level"], logging.WARNING)
        self.assertEqual(emitted["run_id"], RUN_ID)
        self.assertEqual(emitted["evidence_id"], first.evidence_id)

    def test_default_construction_still_dedupes_without_a_logger(self) -> None:
        store = EvidenceStore()
        first = _changed_file_evidence(path="services/checkout.py")
        second = _changed_file_evidence(path="services/checkout_v2.py")

        store.put(first)
        store.put(second)

        self.assertIs(store.get(first.evidence_id), first)


if __name__ == "__main__":
    unittest.main()
