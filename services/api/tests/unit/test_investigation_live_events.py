import json
import logging
import unittest
from uuid import uuid4

from opentelemetry import metrics, trace

from app.explanations import LLMTokenUsage
from app.observability.live_event_broker import LiveEventBroker
from app.observability.runtime_telemetry import RuntimeTelemetry
from app.observability.structured_logging import StructuredEventLogger
from tests.telemetry_support import create_telemetry_harness


class InvestigationLiveEventTests(unittest.TestCase):
    def test_tool_call_completed_event_carries_run_id_tool_id_and_outcome(self) -> None:
        harness = create_telemetry_harness()
        try:
            run_id = uuid4()
            harness.telemetry.record_investigation_tool_call(run_id, "get_incident", "observed")
        finally:
            harness.shutdown()

        record = json.loads(harness.log_stream.getvalue())
        self.assertEqual(record["event"], "investigation.tool.call_completed")
        self.assertEqual(record["run_id"], str(run_id))
        self.assertEqual(record["tool_id"], "get_incident")
        self.assertEqual(record["tool_outcome"], "observed")
        self.assertEqual(record["level"], "info")

    def test_a_failed_tool_call_is_logged_at_warning(self) -> None:
        harness = create_telemetry_harness()
        try:
            harness.telemetry.record_investigation_tool_call(uuid4(), "get_incident", "failed")
        finally:
            harness.shutdown()

        record = json.loads(harness.log_stream.getvalue())
        self.assertEqual(record["level"], "warning")

    def test_round_planned_and_completed_events_carry_the_round_number(self) -> None:
        harness = create_telemetry_harness()
        try:
            run_id = uuid4()
            harness.telemetry.record_investigation_round(run_id, 1, completed=False)
            harness.telemetry.record_investigation_round(run_id, 1, completed=True)
        finally:
            harness.shutdown()

        lines = [
            json.loads(line)
            for line in harness.log_stream.getvalue().strip().splitlines()
        ]
        self.assertEqual(lines[0]["event"], "investigation.round.planned")
        self.assertEqual(lines[0]["round_number"], 1)
        self.assertFalse(lines[0]["round_completed"])
        self.assertEqual(lines[1]["event"], "investigation.round.completed")
        self.assertTrue(lines[1]["round_completed"])

    def test_llm_token_usage_event_carries_real_provider_counts(self) -> None:
        harness = create_telemetry_harness()
        try:
            run_id = uuid4()
            harness.telemetry.record_llm_token_usage(
                run_id,
                "planner",
                LLMTokenUsage(input_tokens=120, output_tokens=40, total_tokens=160),
                round_number=2,
            )
        finally:
            harness.shutdown()

        record = json.loads(harness.log_stream.getvalue())
        self.assertEqual(record["event"], "llm.token_usage")
        self.assertEqual(record["run_id"], str(run_id))
        self.assertEqual(record["role"], "planner")
        self.assertEqual(record["round_number"], 2)
        self.assertEqual(record["input_tokens"], 120)
        self.assertEqual(record["output_tokens"], 40)
        self.assertEqual(record["total_tokens"], 160)
        self.assertEqual(record["level"], "info")

    def test_llm_token_usage_with_no_reported_usage_emits_nothing(self) -> None:
        harness = create_telemetry_harness()
        try:
            harness.telemetry.record_llm_token_usage(uuid4(), "hypothesis", None)
        finally:
            harness.shutdown()

        self.assertEqual(harness.log_stream.getvalue(), "")

    def test_llm_token_usage_with_a_disallowed_role_degrades_to_a_telemetry_warning(
        self,
    ) -> None:
        harness = create_telemetry_harness()
        try:
            harness.telemetry.record_llm_token_usage(
                uuid4(),
                "not_a_real_role",
                LLMTokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            )
        finally:
            harness.shutdown()

        record = json.loads(harness.log_stream.getvalue())
        self.assertEqual(record["event"], "runtime.telemetry.export_failed")
        self.assertEqual(record["level"], "warning")

    def test_diagnostic_failure_event_reaches_a_broker_subscriber(self) -> None:
        broker = LiveEventBroker()
        event_logger = StructuredEventLogger(logging.Logger("test.diagnostic"))
        event_logger.set_broker(broker)
        telemetry = RuntimeTelemetry(
            trace.NoOpTracerProvider().get_tracer("test"),
            metrics.NoOpMeterProvider().get_meter("test"),
            event_logger,
        )
        run_id = uuid4()
        queue = broker.subscribe(str(run_id))

        telemetry.record_investigation_diagnostic_failure(
            run_id,
            "investigation.hypothesis.failed",
            llm_provider="fake",
            failure_code="provider_failure",
        )

        published = queue.get_nowait()
        self.assertEqual(published["event"], "investigation.hypothesis.failed")
        self.assertEqual(published["run_id"], str(run_id))
        self.assertEqual(published["failure_code"], "provider_failure")


if __name__ == "__main__":
    unittest.main()
