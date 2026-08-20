import unittest
from datetime import UTC, datetime

from app.connectors.fakes import FakeJiraConnector
from app.connectors.github_code_fakes import (
    COMMIT_EVIDENCE_FIXTURES,
    CHANGED_FILE_EVIDENCE_FIXTURES,
    FIXTURE_PULL_REQUEST,
    FakeGitHubCodeEvidenceSource,
)
from app.connectors.incident_fakes import (
    DEPLOYMENT_EVIDENCE_FIXTURES,
    FAILURE_LOCATION_EVIDENCE_FIXTURES,
    INCIDENT_EVIDENCE_FIXTURES,
    DEPLOYMENT_REQUEST,
    INCIDENT_REQUEST,
    TELEMETRY_REQUEST,
    FakeIncidentSource,
)
from app.investigations import (
    DeterministicBaseline,
    DiffHunkEvidenceContent,
    InvestigationRequest,
    MissingInformationKind,
    ToolInvoker,
)
from app.investigations.baseline import DuplicateEvidenceIdError, EvidenceAccumulator
from app.investigations.fact_derivation import derive_facts
from app.tools import build_tool_adapters, build_tool_registry


def baseline(incident_source: FakeIncidentSource, github_source: FakeGitHubCodeEvidenceSource | None = None) -> DeterministicBaseline:
    adapters = build_tool_adapters(github_source or FakeGitHubCodeEvidenceSource(), incident_source, FakeJiraConnector())
    return DeterministicBaseline(ToolInvoker(build_tool_registry(adapters), adapters), incident_source)


class DeterministicBaselineTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _recording_baseline(calls: list[str]) -> DeterministicBaseline:
        class RecordingTool:
            def __init__(self, tool) -> None:
                self.definition = tool.definition
                self._tool = tool

            async def execute(self, arguments):
                calls.append(self.definition.tool_id.value)
                return await self._tool.execute(arguments)

        source = FakeIncidentSource()
        adapters = build_tool_adapters(FakeGitHubCodeEvidenceSource(), source, FakeJiraConnector())
        recorded = {tool_id: RecordingTool(tool) for tool_id, tool in adapters.items()}
        return DeterministicBaseline(ToolInvoker(build_tool_registry(adapters), recorded), source)

    async def test_canonical_run_uses_fixed_tools_and_derives_only_supported_facts(self) -> None:
        original = CHANGED_FILE_EVIDENCE_FIXTURES[FIXTURE_PULL_REQUEST]
        hunk = original[1].model_copy(update={
            "content": DiffHunkEvidenceContent(
                repository_owner="octo-org", repository_name="analytics", pull_request_number=42,
                file_path="services/checkout.py", old_start=87, old_count=1,
                new_start=87, new_count=1, lines=original[1].content.lines,
            )
        })
        github = FakeGitHubCodeEvidenceSource(changed_file_fixtures={FIXTURE_PULL_REQUEST: (original[0], hunk)})
        result = await baseline(FakeIncidentSource(), github).investigate(
            InvestigationRequest(
                repository_owner="octo-org", repository_name="analytics",
                incident_summary="Checkout failures", incident_reference=INCIDENT_REQUEST.incident_reference,
                deployment_reference=DEPLOYMENT_REQUEST.deployment_reference,
                pull_request_number=42, telemetry_window=TELEMETRY_REQUEST,
            )
        )

        self.assertEqual(
            [fact.fact_type for fact in result.facts],
            [
                "deployment_preceded_incident", "deployment_references_commit",
                "commit_associated_with_pull_request", "changed_file",
                "changed_file_matches_failure_file",
                "changed_hunk_overlaps_failure_line",
            ],
        )
        self.assertEqual(result.hypotheses, ())
        self.assertEqual(result.missing_information, ())
        self.assertEqual(result, await baseline(FakeIncidentSource(), github).investigate(
            InvestigationRequest(repository_owner="octo-org", repository_name="analytics", incident_summary="Checkout failures", incident_reference=INCIDENT_REQUEST.incident_reference, deployment_reference=DEPLOYMENT_REQUEST.deployment_reference, pull_request_number=42, telemetry_window=TELEMETRY_REQUEST)
        ))

    async def test_missing_deployment_keeps_incident_evidence_and_does_not_crash(self) -> None:
        result = await baseline(FakeIncidentSource()).investigate(
            InvestigationRequest(repository_owner="octo-org", repository_name="analytics", incident_summary="Checkout failures", incident_reference=INCIDENT_REQUEST.incident_reference)
        )

        self.assertTrue(result.evidence)
        self.assertIn(MissingInformationKind.DEPLOYMENT_MAPPING_UNAVAILABLE, [item.kind for item in result.missing_information])

    async def test_source_failure_is_missing_information_not_fake_evidence(self) -> None:
        result = await baseline(FakeIncidentSource(incident_fixtures={})).investigate(
            InvestigationRequest(repository_owner="octo-org", repository_name="analytics", incident_summary="Checkout failures", incident_reference=INCIDENT_REQUEST.incident_reference)
        )

        self.assertNotIn("incident", [item.kind.value for item in result.evidence])
        self.assertIn("stack_frame", [item.kind.value for item in result.evidence])
        self.assertIn(MissingInformationKind.SOURCE_DATA_UNAVAILABLE, [item.kind for item in result.missing_information])

    async def test_fixed_tool_order_and_conditional_deployment_branch_are_explicit(self) -> None:
        # Recording adapters prove orchestration order without changing the
        # production adapters or making network calls.
        calls: list[str] = []
        request = InvestigationRequest(
            repository_owner="octo-org", repository_name="analytics", incident_summary="Checkout failures",
            incident_reference=INCIDENT_REQUEST.incident_reference, deployment_reference=DEPLOYMENT_REQUEST.deployment_reference,
            pull_request_number=42, telemetry_window=TELEMETRY_REQUEST,
        )
        await self._recording_baseline(calls).investigate(request)
        self.assertEqual(calls, ["get_incident", "get_deployments", "query_telemetry", "get_commit", "get_pull_request", "get_diff"])

        calls.clear()
        await self._recording_baseline(calls).investigate(request.model_copy(update={"deployment_reference": None, "pull_request_number": None}))
        self.assertEqual(calls, ["get_incident", "query_telemetry"])


class FactDerivationTests(unittest.TestCase):
    # These unit cases keep relationship predicates separate from source calls,
    # so a failed assertion identifies a derivation rule rather than a fixture lookup.
    def setUp(self) -> None:
        self.incident = INCIDENT_EVIDENCE_FIXTURES[INCIDENT_REQUEST]
        self.deployment = DEPLOYMENT_EVIDENCE_FIXTURES[DEPLOYMENT_REQUEST]
        self.commit = COMMIT_EVIDENCE_FIXTURES[next(iter(COMMIT_EVIDENCE_FIXTURES))]
        self.changed_file, self.hunk = CHANGED_FILE_EVIDENCE_FIXTURES[FIXTURE_PULL_REQUEST]
        self.frame = FAILURE_LOCATION_EVIDENCE_FIXTURES[next(iter(FAILURE_LOCATION_EVIDENCE_FIXTURES))]

    def test_temporal_fact_requires_strict_precedence(self) -> None:
        after = self.deployment.model_copy(update={"content": self.deployment.content.model_copy(update={"deployed_at": datetime(2026, 8, 17, 12, 0, tzinfo=UTC)})})
        equal = self.deployment.model_copy(update={"content": self.deployment.content.model_copy(update={"deployed_at": self.incident.content.started_at})})

        self.assertEqual([fact.fact_type for fact in derive_facts((self.incident, self.deployment))], ["deployment_preceded_incident"])
        self.assertEqual(derive_facts((self.incident, after)), ())
        self.assertEqual(derive_facts((self.incident, equal)), ())

    def test_deployment_commit_and_pr_require_exact_sha_association(self) -> None:
        pull_request = CHANGED_FILE_EVIDENCE_FIXTURES[FIXTURE_PULL_REQUEST]  # Preserve fixture ordering context.
        from app.connectors.github_code_fakes import PULL_REQUEST_EVIDENCE_FIXTURES
        pr = PULL_REQUEST_EVIDENCE_FIXTURES[FIXTURE_PULL_REQUEST]
        mismatch = self.commit.model_copy(update={"content": self.commit.content.model_copy(update={"commit_sha": "d" * 40})})

        facts = derive_facts((self.deployment, self.commit, pr))
        self.assertEqual([fact.fact_type for fact in facts], ["deployment_references_commit", "commit_associated_with_pull_request"])
        self.assertEqual(derive_facts((self.deployment, mismatch, pr)), ())
        self.assertEqual(pull_request[0].kind.value, "changed_file")

    def test_code_facts_require_matching_path_and_safe_new_line_range(self) -> None:
        overlapping = self.hunk.model_copy(update={"content": DiffHunkEvidenceContent(repository_owner="octo-org", repository_name="analytics", pull_request_number=42, file_path="services/checkout.py", old_start=87, old_count=1, new_start=87, new_count=1, lines=self.hunk.content.lines)})
        outside = overlapping.model_copy(update={"content": overlapping.content.model_copy(update={"new_start": 88})})
        no_patch = self.changed_file.model_copy(update={"content": self.changed_file.content.model_copy(update={"patch_available": False})})
        other_path = self.changed_file.model_copy(update={"content": self.changed_file.content.model_copy(update={"path": "services/payments.py"})})

        facts = derive_facts((self.changed_file, overlapping, self.frame))
        self.assertEqual([fact.fact_type for fact in facts], ["changed_file", "changed_file_matches_failure_file", "changed_hunk_overlaps_failure_line"])
        self.assertEqual([fact.fact_type for fact in derive_facts((self.changed_file, outside, self.frame))], ["changed_file", "changed_file_matches_failure_file"])
        self.assertEqual([fact.fact_type for fact in derive_facts((no_patch, overlapping, self.frame))], ["changed_file", "changed_file_matches_failure_file"])
        self.assertEqual([fact.fact_type for fact in derive_facts((other_path, overlapping, self.frame))], ["changed_file"])

    def test_facts_preserve_evidence_references_and_accumulator_rejects_duplicates(self) -> None:
        overlapping = self.hunk.model_copy(update={"content": self.hunk.content.model_copy(update={"old_start": 87, "new_start": 87})})
        facts = derive_facts((self.changed_file, overlapping, self.frame))
        self.assertEqual(facts[2].evidence_reference_ids, tuple(sorted((self.changed_file.evidence_id, overlapping.evidence_id, self.frame.evidence_id))))
        accumulator = EvidenceAccumulator()
        accumulator.add((self.incident,))
        with self.assertRaises(DuplicateEvidenceIdError):
            accumulator.add((self.incident,))


if __name__ == "__main__":
    unittest.main()
