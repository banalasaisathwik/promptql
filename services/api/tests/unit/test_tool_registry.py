import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from app.connectors.errors import (
    ConnectorUnavailableError,
    GitHubRateLimitedError,
    SentryNotFoundError,
)
from app.connectors.fakes import FakeJiraConnector
from app.connectors.github_code_fakes import (
    FIXTURE_COMMIT_REQUEST,
    FIXTURE_PULL_REQUEST,
    FakeGitHubCodeEvidenceSource,
)
from app.connectors.incident_fakes import (
    DEPLOYMENT_REQUEST,
    FAILURE_LOCATION_REQUEST,
    INCIDENT_REQUEST,
    TELEMETRY_REQUEST,
    FakeIncidentSource,
)
from app.connectors.models import TelemetrySignal
from app.connectors.jira_fixtures import JIRA_FIXTURES
from app.investigations.evidence_store import EvidenceStore
from app.tools import (
    DuplicateToolError,
    GetCommitDiffTool,
    GetCommitTool,
    GetDiffTool,
    GetFailureLocationTool,
    GetDeploymentsTool,
    GetIncidentTool,
    GetJiraIssueInput,
    GetJiraIssueTool,
    GetPullRequestTool,
    InvestigationToolId,
    InvalidToolArgumentsError,
    QueryTelemetryTool,
    TOOL_DEFINITIONS,
    ToolFailure,
    ToolFailureCode,
    ToolOutcome,
    ToolRegistry,
    UnknownToolError,
    build_tool_adapters,
    build_tool_registry,
)


class ToolDefinitionTests(unittest.TestCase):
    def test_definition_exposes_stable_id_description_and_input_schema(self) -> None:
        definition = TOOL_DEFINITIONS[0]

        self.assertEqual(definition.tool_id, InvestigationToolId.GET_COMMIT)
        self.assertTrue(definition.read_only)
        self.assertIn("commit_sha", definition.input_schema["properties"])
        self.assertNotIn("openai", str(definition.input_schema).lower())

    def test_commit_diff_definition_is_read_only_and_scoped_by_commit_sha(self) -> None:
        definition = next(
            item for item in TOOL_DEFINITIONS
            if item.tool_id == InvestigationToolId.GET_COMMIT_DIFF
        )

        self.assertTrue(definition.read_only)
        self.assertIn("commit_sha", definition.input_schema["properties"])
        self.assertNotIn("pull_request_number", definition.input_schema["properties"])

    def test_input_contract_is_strict_and_constrained(self) -> None:
        definition = next(
            item for item in TOOL_DEFINITIONS
            if item.tool_id == InvestigationToolId.GET_COMMIT
        )

        with self.assertRaises(ValueError):
            definition.validate_arguments(
                {
                    "repository_owner": "octo-org",
                    "repository_name": "analytics",
                    "commit_sha": "a" * 40,
                    "raw_query": "provider syntax must not be accepted",
                }
            )

    def test_tool_result_rejects_inconsistent_outcome(self) -> None:
        from app.tools import ToolResult

        with self.assertRaises(ValidationError):
            ToolResult(tool_id=InvestigationToolId.GET_COMMIT, outcome=ToolOutcome.FAILED)

    def test_every_failure_code_has_a_deterministic_retry_decision(self) -> None:
        retryable_codes = {
            ToolFailureCode.RATE_LIMITED,
            ToolFailureCode.TIMEOUT,
            ToolFailureCode.UPSTREAM_UNAVAILABLE,
        }

        for code in ToolFailureCode:
            with self.subTest(code=code):
                failure = ToolFailure(code=code, message="sanitized failure")
                self.assertEqual(failure.retryable, code in retryable_codes)


class ToolRegistryTests(unittest.TestCase):
    def test_registry_lists_definitions_deterministically(self) -> None:
        registry = ToolRegistry(reversed(TOOL_DEFINITIONS))

        self.assertEqual(
            [item.tool_id for item in registry.list()],
            sorted(item.tool_id for item in TOOL_DEFINITIONS),
        )
        self.assertEqual(registry.get("get_diff").tool_id, InvestigationToolId.GET_DIFF)

    def test_duplicate_and_unknown_tools_are_explicit(self) -> None:
        registry = ToolRegistry([TOOL_DEFINITIONS[0]])

        with self.assertRaises(DuplicateToolError):
            registry.register(TOOL_DEFINITIONS[0])
        with self.assertRaises(UnknownToolError):
            registry.get("does_not_exist")

    def test_registries_do_not_share_mutable_state(self) -> None:
        first = ToolRegistry()
        second = ToolRegistry()

        first.register(TOOL_DEFINITIONS[0])

        self.assertEqual(second.list(), ())


class ToolAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_github_adapters_return_normalized_evidence(self) -> None:
        source = FakeGitHubCodeEvidenceSource()
        store = EvidenceStore()

        commit_result = await GetCommitTool(source, store).execute(
            FIXTURE_COMMIT_REQUEST.model_dump()
        )
        pull_request_result = await GetPullRequestTool(source, store).execute(
            FIXTURE_PULL_REQUEST.model_dump()
        )
        diff_result = await GetDiffTool(source, store).execute(
            FIXTURE_PULL_REQUEST.model_dump()
        )
        commit_diff_result = await GetCommitDiffTool(source, store).execute(
            FIXTURE_COMMIT_REQUEST.model_dump()
        )

        self.assertEqual(commit_result.outcome, ToolOutcome.OBSERVED)
        self.assertEqual(store.get(commit_result.evidence_ids[0]).kind.value, "commit")
        self.assertEqual(store.get(pull_request_result.evidence_ids[0]).kind.value, "pull_request")
        self.assertEqual(len(diff_result.evidence_ids), 2)
        self.assertEqual(commit_diff_result.outcome, ToolOutcome.OBSERVED)
        self.assertEqual(
            tuple(store.get(evidence_id).kind.value for evidence_id in commit_diff_result.evidence_ids),
            ("commit_changed_file", "commit_diff_hunk"),
        )
        self.assertEqual(
            store.get(commit_diff_result.evidence_ids[0]).content.commit_sha,
            FIXTURE_COMMIT_REQUEST.commit_sha,
        )

    async def test_incident_adapters_use_existing_bounded_requests(self) -> None:
        source = FakeIncidentSource()
        store = EvidenceStore()

        incident_result = await GetIncidentTool(source, store).execute(
            INCIDENT_REQUEST.model_dump()
        )
        deployment_result = await GetDeploymentsTool(source, store).execute(
            DEPLOYMENT_REQUEST.model_dump()
        )
        telemetry_result = await QueryTelemetryTool(source, store).execute(
            TELEMETRY_REQUEST.model_dump()
        )
        failure_location_result = await GetFailureLocationTool(source, store).execute(
            FAILURE_LOCATION_REQUEST.model_dump()
        )

        self.assertEqual(store.get(incident_result.evidence_ids[0]).kind.value, "incident")
        self.assertEqual(store.get(deployment_result.evidence_ids[0]).kind.value, "deployment")
        self.assertEqual(store.get(telemetry_result.evidence_ids[0]).content.event_count, 17)
        self.assertEqual(
            store.get(failure_location_result.evidence_ids[0]).content.file_path,
            "services/checkout.py",
        )

    async def test_jira_adapter_normalizes_connector_result_to_evidence(self) -> None:
        issue = next(iter(JIRA_FIXTURES.values()))
        store = EvidenceStore()

        result = await GetJiraIssueTool(FakeJiraConnector(), store).execute(
            GetJiraIssueInput(issue_key=issue.issue_key).model_dump()
        )

        self.assertEqual(store.get(result.evidence_ids[0]).source.value, "jira")
        self.assertEqual(store.get(result.evidence_ids[0]).content.issue_key, issue.issue_key)

    async def test_invalid_arguments_fail_before_capability_execution(self) -> None:
        class MustNotRunSource(FakeIncidentSource):
            async def get_incident_evidence(self, request):
                raise AssertionError("source should not run for invalid arguments")

        with self.assertRaises(InvalidToolArgumentsError):
            await GetIncidentTool(MustNotRunSource(), EvidenceStore()).execute(
                {"incident_reference": "incident:test", "extra": "rejected"}
            )

    async def test_source_failure_is_typed_and_sanitized(self) -> None:
        source = FakeIncidentSource(incident_fixtures={})

        result = await GetIncidentTool(source, EvidenceStore()).execute(
            INCIDENT_REQUEST.model_dump()
        )

        self.assertEqual(result.outcome, ToolOutcome.FAILED)
        self.assertEqual(result.failure.code, ToolFailureCode.NOT_FOUND)
        self.assertFalse(result.failure.retryable)
        self.assertNotIn("incident:test", result.failure.message)

    async def test_commit_diff_source_failure_is_typed_and_sanitized(self) -> None:
        source = FakeGitHubCodeEvidenceSource(commit_changed_file_fixtures={})

        result = await GetCommitDiffTool(source, EvidenceStore()).execute(
            FIXTURE_COMMIT_REQUEST.model_dump()
        )

        self.assertEqual(result.outcome, ToolOutcome.FAILED)
        self.assertEqual(result.failure.code, ToolFailureCode.NOT_FOUND)

    async def test_transient_connector_failure_is_retryable(self) -> None:
        class RateLimitedGitHubSource:
            async def get_commit_evidence(self, request):
                raise GitHubRateLimitedError()

        result = await GetCommitTool(RateLimitedGitHubSource(), EvidenceStore()).execute(
            FIXTURE_COMMIT_REQUEST.model_dump()
        )

        self.assertEqual(result.failure.code, ToolFailureCode.RATE_LIMITED)
        self.assertTrue(result.failure.retryable)

    async def test_capability_unavailability_is_distinct_from_source_failure(self) -> None:
        class UnavailableSource(FakeIncidentSource):
            async def get_incident_evidence(self, request):
                raise ConnectorUnavailableError("incident")

        result = await GetIncidentTool(UnavailableSource(), EvidenceStore()).execute(
            INCIDENT_REQUEST.model_dump()
        )

        self.assertEqual(result.failure.code, ToolFailureCode.CAPABILITY_UNAVAILABLE)

    async def test_sentry_failures_remain_typed_for_every_sentry_adapter(self) -> None:
        class NotFoundSentrySource(FakeIncidentSource):
            async def get_incident_evidence(self, request):
                raise SentryNotFoundError()

            async def get_deployment_evidence(self, request):
                raise SentryNotFoundError()

            async def get_failure_location_evidence(self, request):
                raise SentryNotFoundError()

            async def get_telemetry_window_evidence(self, request):
                raise SentryNotFoundError()

        source = NotFoundSentrySource()
        cases = (
            (GetIncidentTool(source, EvidenceStore()), INCIDENT_REQUEST),
            (GetDeploymentsTool(source, EvidenceStore()), DEPLOYMENT_REQUEST),
            (GetFailureLocationTool(source, EvidenceStore()), FAILURE_LOCATION_REQUEST),
            (QueryTelemetryTool(source, EvidenceStore()), TELEMETRY_REQUEST),
        )

        for tool, request in cases:
            with self.subTest(tool=tool.definition.tool_id):
                result = await tool.execute(request.model_dump())
                self.assertEqual(result.outcome, ToolOutcome.FAILED)
                self.assertEqual(result.failure.code, ToolFailureCode.NOT_FOUND)
                self.assertNotIn("Sentry", result.failure.message)

    async def test_telemetry_input_keeps_time_and_signal_structured(self) -> None:
        with self.assertRaises(InvalidToolArgumentsError):
            await QueryTelemetryTool(FakeIncidentSource(), EvidenceStore()).execute(
                {
                    "service": "checkout-api",
                    "signal": TelemetrySignal.LOG_EVENTS,
                    "start_time": datetime(2026, 8, 17, 11, 45, tzinfo=UTC),
                    "end_time": datetime(2026, 8, 17, 11, 40, tzinfo=UTC),
                }
            )


class ToolCompositionTests(unittest.IsolatedAsyncioTestCase):
    async def test_composed_adapters_and_registry_share_the_same_surface(self) -> None:
        adapters = build_tool_adapters(
            FakeGitHubCodeEvidenceSource(),
            FakeIncidentSource(),
            FakeJiraConnector(),
            EvidenceStore(),
        )
        registry = build_tool_registry(adapters)

        self.assertEqual(set(adapters), {item.tool_id for item in registry.list()})
        self.assertEqual(
            await adapters["get_deployments"].execute(DEPLOYMENT_REQUEST.model_dump()),
            await adapters["get_deployments"].execute(DEPLOYMENT_REQUEST.model_dump()),
        )


if __name__ == "__main__":
    unittest.main()
