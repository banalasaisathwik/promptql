from app.investigations.models import Evidence


class EvidenceStore:
    def __init__(self) -> None:
        self._evidence_by_id: dict[str, Evidence] = {}

    def put(self, evidence: Evidence) -> str:
        self._evidence_by_id.setdefault(evidence.evidence_id, evidence)
        return evidence.evidence_id

    def get(self, evidence_id: str) -> Evidence:
        return self._evidence_by_id[evidence_id]

    def get_many(self, evidence_ids: tuple[str, ...]) -> tuple[Evidence, ...]:
        return tuple(self._evidence_by_id[evidence_id] for evidence_id in evidence_ids)
