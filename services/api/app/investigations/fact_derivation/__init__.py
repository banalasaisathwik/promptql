from app.investigations import Evidence, FactSet
from app.investigations.fact_derivation.code_change import derive_code_failure_facts
from app.investigations.fact_derivation.deployment import derive_deployment_code_facts
from app.investigations.fact_derivation.temporal import derive_temporal_facts


def derive_facts(evidence: tuple[Evidence, ...]) -> FactSet:
    """Combine independently testable deterministic relationship rules."""
    facts = (
        *derive_temporal_facts(evidence),
        *derive_deployment_code_facts(evidence),
        *derive_code_failure_facts(evidence),
    )
    return tuple({fact.fact_id: fact for fact in facts}.values())


__all__ = ["derive_code_failure_facts", "derive_deployment_code_facts", "derive_facts", "derive_temporal_facts"]
