import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from app.connectors.errors import ConnectorUnavailableError
from app.connectors.fakes import FakeJiraConnector
from app.connectors.github_code_fakes import (
    FIXTURE_COMMIT_REQUEST,
    FIXTURE_PULL_REQUEST,
    FakeGitHubCodeEvidenceSource,
)
from app.connectors.incident_fakes import (
    DEPLOYMENT_REQUEST,
    INCIDENT_REQUEST,
    TELEMETRY_REQUEST,
    FakeIncidentSource,
)
from app.connectors.models import TelemetrySignal
from app.connectors.jira_fixtures import JIRA_FIXTURES
from app.tools import (
    DuplicateToolError,
    GetCommitTool,
    GetDiffTool,
    GetDeploymentsTool,
    GetIncidentTool,
    GetJiraIssueInput,
    GetJiraIssueTool,
    GetPullRequestTool,
    InvestigationToolId,
    InvalidToolArgumentsError,
    QueryTelemetryTool,
    TOOL_DEFINITIONS,
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

        commit_result = await GetCommitTool(source).execute(
            FIXTURE_COMMIT_REQUEST.model_dump()
        )
        pull_request_result = await GetPullRequestTool(source).execute(
            FIXTURE_PULL_REQUEST.model_dump()
        )
        diff_result = await GetDiffTool(source).execute(
            FIXTURE_PULL_REQUEST.model_dump()
        )

        self.assertEqual(commit_result.outcome, ToolOutcome.OBSERVED)
        self.assertEqual(commit_result.evidence[0].kind.value, "commit")
        self.assertEqual(pull_request_result.evidence[0].kind.value, "pull_request")
        self.assertEqual(len(diff_result.evidence), 2)

    async def test_incident_adapters_use_existing_bounded_requests(self) -> None:
        source = FakeIncidentSource()

        incident_result = await GetIncidentTool(source).execute(
            INCIDENT_REQUEST.model_dump()
        )
        deployment_result = await GetDeploymentsTool(source).execute(
            DEPLOYMENT_REQUEST.model_dump()
        )
        telemetry_result = await QueryTelemetryTool(source).execute(
            TELEMETRY_REQUEST.model_dump()
        )

        self.assertEqual(incident_result.evidence[0].kind.value, "incident")
        self.assertEqual(deployment_result.evidence[0].kind.value, "deployment")
        self.assertEqual(telemetry_result.evidence[0].content.event_count, 17)

    async def test_jira_adapter_normalizes_connector_result_to_evidence(self) -> None:
        issue = next(iter(JIRA_FIXTURES.values()))

        result = await GetJiraIssueTool(FakeJiraConnector()).execute(
            GetJiraIssueInput(issue_key=issue.issue_key).model_dump()
        )

        self.assertEqual(result.evidence[0].source.value, "jira")
        self.assertEqual(result.evidence[0].content.issue_key, issue.issue_key)

    async def test_invalid_arguments_fail_before_capability_execution(self) -> None:
        class MustNotRunSource(FakeIncidentSource):
            async def get_incident_evidence(self, request):
                raise AssertionError("source should not run for invalid arguments")

        with self.assertRaises(InvalidToolArgumentsError):
            await GetIncidentTool(MustNotRunSource()).execute(
                {"incident_reference": "incident:test", "extra": "rejected"}
            )

    async def test_source_failure_is_typed_and_sanitized(self) -> None:
        source = FakeIncidentSource(incident_fixtures={})

        result = await GetIncidentTool(source).execute(
            INCIDENT_REQUEST.model_dump()
        )

        self.assertEqual(result.outcome, ToolOutcome.FAILED)
        self.assertEqual(result.failure.code, ToolFailureCode.SOURCE_FAILURE)
        self.assertNotIn("incident:test", result.failure.message)

    async def test_capability_unavailability_is_distinct_from_source_failure(self) -> None:
        class UnavailableSource(FakeIncidentSource):
            async def get_incident_evidence(self, request):
                raise ConnectorUnavailableError("incident")

        result = await GetIncidentTool(UnavailableSource()).execute(
            INCIDENT_REQUEST.model_dump()
        )

        self.assertEqual(result.failure.code, ToolFailureCode.CAPABILITY_UNAVAILABLE)

    async def test_telemetry_input_keeps_time_and_signal_structured(self) -> None:
        with self.assertRaises(InvalidToolArgumentsError):
            await QueryTelemetryTool(FakeIncidentSource()).execute(
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
        )
        registry = build_tool_registry(adapters)

        self.assertEqual(set(adapters), {item.tool_id for item in registry.list()})
        self.assertEqual(
            await adapters["get_deployments"].execute(DEPLOYMENT_REQUEST.model_dump()),
            await adapters["get_deployments"].execute(DEPLOYMENT_REQUEST.model_dump()),
        )


if __name__ == "__main__":
    unittest.main()
