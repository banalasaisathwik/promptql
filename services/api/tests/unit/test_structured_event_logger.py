import asyncio
import io
import logging
import unittest
from uuid import UUID

from app.observability.live_event_broker import LiveEventBroker
from app.observability.structured_logging import StructuredEventLogger


def _logger(stream: io.StringIO) -> logging.Logger:
    test_logger = logging.Logger("promptql.structured_event_logger.test")
    test_logger.addHandler(logging.StreamHandler(stream))
    return test_logger


class StructuredEventLoggerBrokerTests(unittest.IsolatedAsyncioTestCase):
    async def test_emit_publishes_to_the_broker_when_a_run_id_field_is_present(self) -> None:
        broker = LiveEventBroker()
        queue = broker.subscribe("11111111-1111-1111-1111-111111111111")
        event_logger = StructuredEventLogger(_logger(io.StringIO()))
        event_logger.set_broker(broker)

        event_logger.emit(
            "plan.validation_rejected",
            logging.WARNING,
            run_id=UUID("11111111-1111-1111-1111-111111111111"),
            failure_category="plan_too_large",
        )

        published = await asyncio.wait_for(queue.get(), timeout=1)
        self.assertEqual(published["event"], "plan.validation_rejected")
        self.assertEqual(published["run_id"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(published["failure_category"], "plan_too_large")

    async def test_emit_without_a_broker_still_logs_and_does_not_raise(self) -> None:
        stream = io.StringIO()
        event_logger = StructuredEventLogger(_logger(stream))

        event_logger.emit("runtime.telemetry.export_failed", logging.WARNING)

        self.assertIn("runtime.telemetry.export_failed", stream.getvalue())

    async def test_emit_without_a_run_id_field_does_not_publish(self) -> None:
        broker = LiveEventBroker()
        queue = broker.subscribe("some-run")
        event_logger = StructuredEventLogger(_logger(io.StringIO()))
        event_logger.set_broker(broker)

        event_logger.emit("runtime.telemetry.export_failed", logging.WARNING, telemetry_signal="metrics")

        self.assertTrue(queue.empty())

    async def test_a_broker_publish_failure_never_suppresses_the_log_line(self) -> None:
        class ExplodingBroker:
            def publish(self, run_id, event) -> None:
                raise RuntimeError("boom")

        stream = io.StringIO()
        event_logger = StructuredEventLogger(_logger(stream))
        event_logger.set_broker(ExplodingBroker())

        event_logger.emit(
            "plan.validation_rejected",
            logging.WARNING,
            run_id=UUID("22222222-2222-2222-2222-222222222222"),
            failure_category="plan_too_large",
        )

        self.assertIn("plan.validation_rejected", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
