import asyncio
import unittest

from app.explanations import FakeLLMClient, LLMStructuredResponse, LLMTokenUsage
from app.investigations import InvestigationRequest
from app.observability.contracts import (
    INVESTIGATION_PLANNING_ROUNDS_METRIC,
    INVESTIGATION_STAGE_DURATION_METRIC,
    INVESTIGATION_TOOL_CALLS_METRIC,
)
from app.runtime import InMemoryRunRepository, RunStatus
from app.workflows import InvestigationWorkflowService
from tests.telemetry_support import create_telemetry_harness


class UsageReportingFakeClient(FakeLLMClient):
    async def generate_typed(self, request):
        response = await super().generate_typed(request)
        return LLMStructuredResponse(
            output=response.output,
            resolved_model="resolved-fake-model",
            token_usage=LLMTokenUsage(
                input_tokens=11,
                output_tokens=7,
                total_tokens=18,
            ),
        )


class InvestigationObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = create_telemetry_harness()

    def tearDown(self) -> None:
        self.harness.shutdown()

    def test_real_fake_trajectory_emits_bounded_stage_hierarchy_and_metrics(self):
        repository = InMemoryRunRepository()
        workflow = InvestigationWorkflowService(
            repository,
            UsageReportingFakeClient(),
            telemetry=self.harness.telemetry,
        )
        pending = asyncio.run(
            workflow.create_persisted_run(
                InvestigationRequest(
                    repository_owner="octo-org",
                    repository_name="analytics",
                    question="Why did checkout start returning 500 errors?",
                    incident_reference="incident:checkout-500",
                    deployment_reference="deployment:1042",
                    pull_request_number=42,
                    service="checkout-api",
                    environment="production",
                )
            )
        )

        completed = asyncio.run(workflow.continue_persisted_run(pending))

        self.assertEqual(completed.status, RunStatus.COMPLETED)
        self.assertIsNotNone(completed.state)
        spans = self.harness.span_exporter.get_finished_spans()
        spans_by_name = {span.name: span for span in spans}
        expected_names = {
            "investigation.investigation",
            "investigation.planning_round",
            "investigation.planner",
            "investigation.plan_validation",
            "investigation.tool_execution",
            "investigation.fact_derivation",
            "investigation.hypothesis_generation",
            "investigation.hypothesis_validation",
            "investigation.code_diagnosis",
            "investigation.code_validation",
            "investigation.render",
            "investigation.termination",
        }
        self.assertTrue(expected_names <= set(spans_by_name))

        root = spans_by_name["investigation.investigation"]
        self.assertEqual(root.attributes["langfuse.trace.name"], "promptql-investigation")
        self.assertTrue(
            all(span.context.trace_id == root.context.trace_id for span in spans)
        )
        llm_spans = [
            span
            for span in spans
            if span.attributes.get("langfuse.observation.type") == "generation"
        ]
        self.assertGreaterEqual(len(llm_spans), 4)
        self.assertTrue(
            all(
                span.attributes["langfuse.observation.model.name"]
                == "resolved-fake-model"
                for span in llm_spans
            )
        )
        self.assertTrue(
            all(span.attributes["promptql.llm.total_tokens"] == 18 for span in llm_spans)
        )
        self.assertTrue(
            all(
                span.attributes["gen_ai.response.model"] == "resolved-fake-model"
                for span in llm_spans
            )
        )
        self.assertTrue(
            all(span.attributes["gen_ai.usage.input_tokens"] == 11 for span in llm_spans)
        )
        self.assertTrue(
            all(span.attributes["gen_ai.usage.output_tokens"] == 7 for span in llm_spans)
        )

        stage_points = self.harness.metric_points(
            INVESTIGATION_STAGE_DURATION_METRIC
        )
        self.assertGreaterEqual(len(stage_points), len(expected_names))
        tool_points = self.harness.metric_points(INVESTIGATION_TOOL_CALLS_METRIC)
        self.assertEqual(
            sum(point.value for point in tool_points),
            completed.state.used_tool_calls,
        )
        round_points = self.harness.metric_points(
            INVESTIGATION_PLANNING_ROUNDS_METRIC
        )
        self.assertEqual(
            sum(point.value for point in round_points),
            len(completed.state.rounds),
        )

        exported = repr(spans) + repr(stage_points + tool_points + round_points)
        self.assertNotIn(completed.request.question, exported)
        self.assertNotIn("raw provider response", exported)
        self.assertNotIn("authorization", exported.lower())


if __name__ == "__main__":
    unittest.main()
