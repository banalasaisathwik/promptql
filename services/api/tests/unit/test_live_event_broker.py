import asyncio
import unittest

from app.observability.live_event_broker import LiveEventBroker


class LiveEventBrokerTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_delivers_to_a_subscribed_queue(self) -> None:
        broker = LiveEventBroker()
        queue = broker.subscribe("run-1")

        broker.publish("run-1", {"event": "plan.validation_rejected"})

        delivered = await asyncio.wait_for(queue.get(), timeout=1)
        self.assertEqual(delivered, {"event": "plan.validation_rejected"})

    async def test_publish_to_an_unsubscribed_run_id_is_a_no_op(self) -> None:
        broker = LiveEventBroker()

        broker.publish("run-without-subscribers", {"event": "runtime.workflow.completed"})

    async def test_publish_fans_out_to_multiple_subscribers(self) -> None:
        broker = LiveEventBroker()
        first_queue = broker.subscribe("run-1")
        second_queue = broker.subscribe("run-1")

        broker.publish("run-1", {"event": "tool.called"})

        self.assertEqual(await asyncio.wait_for(first_queue.get(), timeout=1), {"event": "tool.called"})
        self.assertEqual(await asyncio.wait_for(second_queue.get(), timeout=1), {"event": "tool.called"})

    async def test_unsubscribe_stops_further_delivery(self) -> None:
        broker = LiveEventBroker()
        queue = broker.subscribe("run-1")

        broker.unsubscribe("run-1", queue)
        broker.publish("run-1", {"event": "runtime.workflow.completed"})

        self.assertTrue(queue.empty())

    async def test_publish_discards_silently_when_a_subscriber_queue_is_full(self) -> None:
        broker = LiveEventBroker()
        queue = broker.subscribe("run-1")
        for index in range(queue.maxsize):
            queue.put_nowait({"event": f"filler-{index}"})

        broker.publish("run-1", {"event": "should_be_dropped"})

        self.assertEqual(queue.qsize(), queue.maxsize)


if __name__ == "__main__":
    unittest.main()
