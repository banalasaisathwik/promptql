from collections import deque
from dataclasses import dataclass
from enum import StrEnum

from app.investigations.models import (
    ChangedFileFact,
    ChangedFileMatchesFailureFileFact,
    ChangedHunkOverlapsFailureLineFact,
    CommitAssociatedWithPullRequestFact,
    DeploymentPrecededIncidentFact,
    DeploymentReferencesCommitFact,
    FactSet,
    InvestigationFact,
    InvestigationIdentifier,
)


class EntityType(StrEnum):
    DEPLOYMENT = "deployment"
    INCIDENT = "incident"
    COMMIT = "commit"
    PULL_REQUEST = "pull_request"
    FILE = "file"
    FAILURE_LOCATION = "failure_location"


class RelationshipKind(StrEnum):
    TEMPORAL_PRECEDENCE = "temporal_precedence"
    SHIPS_COMMIT = "ships_commit"
    ASSOCIATED_WITH_PR = "associated_with_pr"
    CHANGED_IN_PULL_REQUEST = "changed_in_pull_request"
    SAME_FILE_AS_FAILURE = "same_file_as_failure"
    OVERLAPS_FAILURE_LINE = "overlaps_failure_line"


@dataclass(frozen=True)
class EntityRef:
    entity_type: EntityType
    entity_id: str


@dataclass(frozen=True)
class RelationshipEdge:
    from_entity: EntityRef
    to_entity: EntityRef
    relationship: RelationshipKind
    fact_id: InvestigationIdentifier


@dataclass(frozen=True)
class RelationshipIndex:
    edges: tuple[RelationshipEdge, ...]
    facts_by_id: dict[InvestigationIdentifier, InvestigationFact]

    def neighbors(self, entity: EntityRef) -> tuple[RelationshipEdge, ...]:
        return tuple(
            edge
            for edge in self.edges
            if entity in (edge.from_entity, edge.to_entity)
        )


def build_relationship_index(facts: FactSet) -> RelationshipIndex:
    edges: list[RelationshipEdge] = []
    for fact in facts:
        if isinstance(fact, DeploymentPrecededIncidentFact):
            edges.append(
                RelationshipEdge(
                    from_entity=EntityRef(EntityType.DEPLOYMENT, fact.deployment_reference),
                    to_entity=EntityRef(EntityType.INCIDENT, fact.incident_reference),
                    relationship=RelationshipKind.TEMPORAL_PRECEDENCE,
                    fact_id=fact.fact_id,
                )
            )
        elif isinstance(fact, DeploymentReferencesCommitFact):
            edges.append(
                RelationshipEdge(
                    from_entity=EntityRef(EntityType.DEPLOYMENT, fact.deployment_reference),
                    to_entity=EntityRef(EntityType.COMMIT, fact.commit_sha),
                    relationship=RelationshipKind.SHIPS_COMMIT,
                    fact_id=fact.fact_id,
                )
            )
        elif isinstance(fact, CommitAssociatedWithPullRequestFact):
            edges.append(
                RelationshipEdge(
                    from_entity=EntityRef(EntityType.COMMIT, fact.commit_sha),
                    to_entity=EntityRef(
                        EntityType.PULL_REQUEST, str(fact.pull_request_number)
                    ),
                    relationship=RelationshipKind.ASSOCIATED_WITH_PR,
                    fact_id=fact.fact_id,
                )
            )
        elif isinstance(fact, ChangedFileFact):
            if fact.pull_request_number is not None:
                edges.append(
                    RelationshipEdge(
                        from_entity=EntityRef(EntityType.FILE, fact.path),
                        to_entity=EntityRef(
                            EntityType.PULL_REQUEST, str(fact.pull_request_number)
                        ),
                        relationship=RelationshipKind.CHANGED_IN_PULL_REQUEST,
                        fact_id=fact.fact_id,
                    )
                )
        elif isinstance(fact, ChangedFileMatchesFailureFileFact):
            edges.append(
                RelationshipEdge(
                    from_entity=EntityRef(EntityType.FILE, fact.file_path),
                    to_entity=EntityRef(EntityType.FAILURE_LOCATION, fact.file_path),
                    relationship=RelationshipKind.SAME_FILE_AS_FAILURE,
                    fact_id=fact.fact_id,
                )
            )
        elif isinstance(fact, ChangedHunkOverlapsFailureLineFact):
            edges.append(
                RelationshipEdge(
                    from_entity=EntityRef(EntityType.FILE, fact.file_path),
                    to_entity=EntityRef(
                        EntityType.FAILURE_LOCATION,
                        f"{fact.file_path}:{fact.line_number}",
                    ),
                    relationship=RelationshipKind.OVERLAPS_FAILURE_LINE,
                    fact_id=fact.fact_id,
                )
            )
    return RelationshipIndex(
        edges=tuple(edges),
        facts_by_id={fact.fact_id: fact for fact in facts},
    )


def find_connecting_facts(
    entity_a: EntityRef,
    entity_b: EntityRef,
    index: RelationshipIndex,
) -> tuple[InvestigationFact, ...] | None:
    if entity_a == entity_b:
        return ()

    visited = {entity_a}
    queue: deque[tuple[EntityRef, tuple[RelationshipEdge, ...]]] = deque([(entity_a, ())])
    while queue:
        current, path = queue.popleft()
        for edge in index.neighbors(current):
            neighbor = edge.to_entity if edge.from_entity == current else edge.from_entity
            if neighbor in visited:
                continue
            next_path = (*path, edge)
            if neighbor == entity_b:
                return tuple(index.facts_by_id[step.fact_id] for step in next_path)
            visited.add(neighbor)
            queue.append((neighbor, next_path))
    return None
