from hashlib import sha256

from app.investigations import Evidence


def fact_id(fact_type: str, *evidence: Evidence) -> str:
    """Create a stable identity from the exact evidence used by one rule."""
    evidence_ids = ":".join(sorted(item.evidence_id for item in evidence))
    digest = sha256(evidence_ids.encode("utf-8")).hexdigest()[:16]
    return f"fact:{fact_type}:{digest}"


def references(*evidence: Evidence) -> tuple[str, ...]:
    return tuple(sorted(item.evidence_id for item in evidence))
