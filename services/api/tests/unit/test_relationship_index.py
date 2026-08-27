import unittest

from app.connectors.fakes import FakeJiraConnector
from app.connectors.github_code_fakes import (
    CHANGED_FILE_EVIDENCE_FIXTURES,
    FIXTURE_PULL_REQUEST,
    FakeGitHubCodeEvidenceSource,
)
from app.connectors.incident_fakes import (
    DEPLOYMENT_REQUEST,
    INCIDENT_REQUEST,
    FakeIncidentSource,
)
from app.investigations import (
    ChangedFileFact,
    ChangedFileMatchesFailureFileFact,
    ChangedHunkOverlapsFailureLineFact,
    CommitAssociatedWithPullRequestFact,
    DeploymentPrecededIncidentFact,
    DeploymentReferencesCommitFact,
    DeterministicBaseline,
    DiffHunkEvidenceContent,
    InvestigationRequest,
    ToolInvoker,
)
from app.investigations.evidence_store import EvidenceStore
from app.investigations.relationship_index import (
    EntityRef,
    EntityType,
    RelationshipEdge,
    RelationshipKind,
    build_relationship_index,
    find_connecting_facts,
)
from app.tools import build_tool_adapters, build_tool_registry


def _facts():
    return (
        DeploymentPrecededIncidentFact(
            fact_id="F_TEMPORAL", evidence_reference_ids=("E_TEMPORAL",),
            deployment_reference="deploy-42", incident_reference="incident-42",
        ),
        DeploymentReferencesCommitFact(
            fact_id="F_SHIPS", evidence_reference_ids=("E_SHIPS",),
            deployment_reference="deploy-42", commit_sha="a" * 40,
        ),
        CommitAssociatedWithPullRequestFact(
            fact_id="F_PR", evidence_reference_ids=("E_PR",),
            commit_sha="a" * 40, pull_request_number=42,
        ),
        ChangedFileFact(
            fact_id="F_CHANGED", evidence_reference_ids=("E_CHANGED",),
            path="checkout.py", change_type="modified",
        ),
        ChangedFileMatchesFailureFileFact(
            fact_id="F_MATCHES", evidence_reference_ids=("E_MATCHES",),
            file_path="checkout.py",
        ),
        ChangedHunkOverlapsFailureLineFact(
            fact_id="F_OVERLAPS", evidence_reference_ids=("E_OVERLAPS",),
            file_path="checkout.py", line_number=87,
        ),
    )


class BuildRelationshipIndexTests(unittest.TestCase):
    def test_index_contains_exactly_the_five_expected_edges(self) -> None:
        index = build_relationship_index(_facts())

        self.assertEqual(len(index.edges), 5)
        actual = {
            (edge.from_entity, edge.relationship, edge.to_entity, edge.fact_id)
            for edge in index.edges
        }
        expected = {
            (
                EntityRef(EntityType.DEPLOYMENT, "deploy-42"),
                RelationshipKind.TEMPORAL_PRECEDENCE,
                EntityRef(EntityType.INCIDENT, "incident-42"),
                "F_TEMPORAL",
            ),
            (
                EntityRef(EntityType.DEPLOYMENT, "deploy-42"),
                RelationshipKind.SHIPS_COMMIT,
                EntityRef(EntityType.COMMIT, "a" * 40),
                "F_SHIPS",
            ),
            (
                EntityRef(EntityType.COMMIT, "a" * 40),
                RelationshipKind.ASSOCIATED_WITH_PR,
                EntityRef(EntityType.PULL_REQUEST, "42"),
                "F_PR",
            ),
            (
                EntityRef(EntityType.FILE, "checkout.py"),
                RelationshipKind.SAME_FILE_AS_FAILURE,
                EntityRef(EntityType.FAILURE_LOCATION, "checkout.py"),
                "F_MATCHES",
            ),
            (
                EntityRef(EntityType.FILE, "checkout.py"),
                RelationshipKind.OVERLAPS_FAILURE_LINE,
                EntityRef(EntityType.FAILURE_LOCATION, "checkout.py:87"),
                "F_OVERLAPS",
            ),
        }
        self.assertEqual(actual, expected)

    def test_changed_file_fact_without_pull_request_number_produces_no_edge(self) -> None:
        index = build_relationship_index(_facts())

        self.assertTrue(
            all(edge.fact_id != "F_CHANGED" for edge in index.edges)
        )

    def test_changed_file_fact_with_pull_request_number_produces_the_bridging_edge(self) -> None:
        facts = (
            *_facts(),
            ChangedFileFact(
                fact_id="F_CHANGED_WITH_PR", evidence_reference_ids=("E_CHANGED_WITH_PR",),
                path="payments.py", change_type="modified", pull_request_number=42,
            ),
        )
        index = build_relationship_index(facts)

        bridging_edges = [edge for edge in index.edges if edge.fact_id == "F_CHANGED_WITH_PR"]
        self.assertEqual(
            bridging_edges,
            [
                RelationshipEdge(
                    from_entity=EntityRef(EntityType.FILE, "payments.py"),
                    to_entity=EntityRef(EntityType.PULL_REQUEST, "42"),
                    relationship=RelationshipKind.CHANGED_IN_PULL_REQUEST,
                    fact_id="F_CHANGED_WITH_PR",
                )
            ],
        )

    def test_facts_by_id_indexes_every_input_fact_including_node_only_facts(self) -> None:
        facts = _facts()
        index = build_relationship_index(facts)

        self.assertEqual(set(index.facts_by_id), {fact.fact_id for fact in facts})

    def test_empty_fact_set_produces_an_empty_index(self) -> None:
        index = build_relationship_index(())

        self.assertEqual(index.edges, ())
        self.assertEqual(index.facts_by_id, {})

    def test_neighbors_are_undirected(self) -> None:
        index = build_relationship_index(_facts())
        deployment = EntityRef(EntityType.DEPLOYMENT, "deploy-42")
        incident = EntityRef(EntityType.INCIDENT, "incident-42")

        from_deployment = {edge.fact_id for edge in index.neighbors(deployment)}
        from_incident = {edge.fact_id for edge in index.neighbors(incident)}

        self.assertIn("F_TEMPORAL", from_deployment)
        self.assertIn("F_TEMPORAL", from_incident)


class FindConnectingFactsTests(unittest.TestCase):
    def test_directly_connected_entities_return_the_single_backing_fact(self) -> None:
        index = build_relationship_index(_facts())

        chain = find_connecting_facts(
            EntityRef(EntityType.FILE, "checkout.py"),
            EntityRef(EntityType.FAILURE_LOCATION, "checkout.py"),
            index,
        )

        self.assertEqual([fact.fact_id for fact in chain], ["F_MATCHES"])

    def test_multi_hop_chain_returns_facts_in_traversal_order(self) -> None:
        index = build_relationship_index(_facts())

        chain = find_connecting_facts(
            EntityRef(EntityType.DEPLOYMENT, "deploy-42"),
            EntityRef(EntityType.PULL_REQUEST, "42"),
            index,
        )

        self.assertEqual([fact.fact_id for fact in chain], ["F_SHIPS", "F_PR"])

    def test_unconnected_entities_return_none(self) -> None:
        index = build_relationship_index(_facts())

        chain = find_connecting_facts(
            EntityRef(EntityType.DEPLOYMENT, "deploy-42"),
            EntityRef(EntityType.FILE, "checkout.py"),
            index,
        )

        self.assertIsNone(chain)

    def test_pull_request_to_file_is_traceable_once_pull_request_number_is_present(self) -> None:
        facts = (
            *_facts(),
            ChangedFileFact(
                fact_id="F_CHANGED_WITH_PR", evidence_reference_ids=("E_CHANGED_WITH_PR",),
                path="checkout.py", change_type="modified", pull_request_number=42,
            ),
        )
        index = build_relationship_index(facts)

        chain = find_connecting_facts(
            EntityRef(EntityType.PULL_REQUEST, "42"),
            EntityRef(EntityType.FILE, "checkout.py"),
            index,
        )

        self.assertEqual([fact.fact_id for fact in chain], ["F_CHANGED_WITH_PR"])

    def test_same_entity_returns_an_empty_chain(self) -> None:
        index = build_relationship_index(_facts())
        entity = EntityRef(EntityType.FILE, "checkout.py")

        self.assertEqual(find_connecting_facts(entity, entity, index), ())

    def test_unknown_entity_returns_none(self) -> None:
        index = build_relationship_index(_facts())

        chain = find_connecting_facts(
            EntityRef(EntityType.DEPLOYMENT, "unknown-deployment"),
            EntityRef(EntityType.INCIDENT, "incident-42"),
            index,
        )

        self.assertIsNone(chain)


class Checkout500FixtureTraversalTests(unittest.IsolatedAsyncioTestCase):
    async def _checkout_500_facts(self):
        original = CHANGED_FILE_EVIDENCE_FIXTURES[FIXTURE_PULL_REQUEST]
        hunk = original[1].model_copy(update={
            "content": DiffHunkEvidenceContent(
                repository_owner="octo-org", repository_name="analytics", pull_request_number=42,
                file_path="services/checkout.py", old_start=87, old_count=1,
                new_start=87, new_count=1, lines=original[1].content.lines,
            )
        })
        github = FakeGitHubCodeEvidenceSource(changed_file_fixtures={FIXTURE_PULL_REQUEST: (original[0], hunk)})
        store = EvidenceStore()
        adapters = build_tool_adapters(github, FakeIncidentSource(), FakeJiraConnector(), store)
        baseline = DeterministicBaseline(
            ToolInvoker(build_tool_registry(adapters), adapters), FakeIncidentSource(), store
        )
        result = await baseline.investigate(
            InvestigationRequest(
                repository_owner="octo-org", repository_name="analytics",
                question="Why are checkout requests failing?",
                incident_reference=INCIDENT_REQUEST.incident_reference,
                deployment_reference=DEPLOYMENT_REQUEST.deployment_reference,
                pull_request_number=42,
            )
        )
        return result.facts

    async def test_deployment_to_pull_request_chain_is_traceable(self) -> None:
        facts = await self._checkout_500_facts()
        index = build_relationship_index(facts)

        chain = find_connecting_facts(
            EntityRef(EntityType.DEPLOYMENT, "deployment:1042"),
            EntityRef(EntityType.PULL_REQUEST, "42"),
            index,
        )

        self.assertEqual(
            [fact.fact_type for fact in chain],
            ["deployment_references_commit", "commit_associated_with_pull_request"],
        )

    async def test_file_to_failure_line_chain_is_traceable(self) -> None:
        facts = await self._checkout_500_facts()
        index = build_relationship_index(facts)

        chain = find_connecting_facts(
            EntityRef(EntityType.FILE, "services/checkout.py"),
            EntityRef(EntityType.FAILURE_LOCATION, "services/checkout.py:87"),
            index,
        )

        self.assertEqual(
            [fact.fact_type for fact in chain],
            ["changed_hunk_overlaps_failure_line"],
        )

    async def test_pull_request_and_file_subgraphs_are_now_connected(self) -> None:
        facts = await self._checkout_500_facts()
        index = build_relationship_index(facts)

        chain = find_connecting_facts(
            EntityRef(EntityType.PULL_REQUEST, "42"),
            EntityRef(EntityType.FILE, "services/checkout.py"),
            index,
        )

        self.assertEqual([fact.fact_type for fact in chain], ["changed_file"])

    async def test_full_deployment_to_failure_chain_is_traceable_end_to_end(self) -> None:
        facts = await self._checkout_500_facts()
        index = build_relationship_index(facts)

        chain = find_connecting_facts(
            EntityRef(EntityType.DEPLOYMENT, "deployment:1042"),
            EntityRef(EntityType.FAILURE_LOCATION, "services/checkout.py"),
            index,
        )

        self.assertEqual(
            [fact.fact_type for fact in chain],
            [
                "deployment_references_commit",
                "commit_associated_with_pull_request",
                "changed_file",
                "changed_file_matches_failure_file",
            ],
        )


if __name__ == "__main__":
    unittest.main()
