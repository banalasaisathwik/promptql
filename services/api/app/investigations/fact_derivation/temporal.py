from app.investigations import (
    DeploymentEvidenceContent,
    DeploymentPrecededIncidentFact,
    Evidence,
    IncidentEvidenceContent,
)
from app.investigations.fact_derivation._ids import fact_id, references


def derive_temporal_facts(evidence: tuple[Evidence, ...]) -> tuple[DeploymentPrecededIncidentFact, ...]:
    # Strict ordering avoids treating equal provider timestamps as evidence of
    # precedence; the fact is temporal association, never causation.
    facts: list[DeploymentPrecededIncidentFact] = []
    deployments = [item for item in evidence if isinstance(item.content, DeploymentEvidenceContent)]
    incidents = [item for item in evidence if isinstance(item.content, IncidentEvidenceContent)]
    for deployment in deployments:
        for incident in incidents:
            if (
                incident.content.started_at is None
                or deployment.content.deployed_at >= incident.content.started_at
            ):
                continue
            facts.append(
                DeploymentPrecededIncidentFact(
                    fact_id=fact_id("deployment-preceded-incident", deployment, incident),
                    evidence_reference_ids=references(deployment, incident),
                    deployment_reference=deployment.content.deployment_reference,
                    incident_reference=incident.content.incident_reference,
                )
            )
    return tuple(facts)
