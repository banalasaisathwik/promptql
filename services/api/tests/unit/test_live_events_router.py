import asyncio
import json
import unittest
from uuid import uuid4

from app.api.v1.live_events_router import _stream_events
from app.observability.live_event_broker import LiveEventBroker


class StreamEventsTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_published_event_is_yielded_as_an_sse_data_line(self) -> None:
        broker = LiveEventBroker()
        run_id = uuid4()
        generator = _stream_events(broker, run_id)

        pending_chunk = asyncio.ensure_future(generator.__anext__())
        await asyncio.sleep(0)
        broker.publish(str(run_id), {"event": "investigation.tool.call_completed", "run_id": str(run_id)})
        chunk = await asyncio.wait_for(pending_chunk, timeout=1)

        self.assertTrue(chunk.startswith("data: "))
        self.assertTrue(chunk.endswith("\n\n"))
        payload = json.loads(chunk[len("data: "):].strip())
        self.assertEqual(payload["event"], "investigation.tool.call_completed")
        self.assertEqual(payload["run_id"], str(run_id))

        await generator.aclose()

    async def test_an_idle_stream_yields_a_keep_alive_comment_after_the_poll_interval(self) -> None:
        broker = LiveEventBroker()
        run_id = uuid4()
        generator = _stream_events(broker, run_id, poll_interval_seconds=0.05)

        chunk = await asyncio.wait_for(generator.__anext__(), timeout=1)

        self.assertEqual(chunk, ": keep-alive\n\n")

        await generator.aclose()

    async def test_cancelling_the_stream_unsubscribes_from_the_broker(self) -> None:
        broker = LiveEventBroker()
        run_id = uuid4()
        generator = _stream_events(broker, run_id)

        pending_chunk = asyncio.ensure_future(generator.__anext__())
        await asyncio.sleep(0)
        self.assertIn(str(run_id), broker._subscribers)

        pending_chunk.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending_chunk

        self.assertNotIn(str(run_id), broker._subscribers)

    async def test_events_for_a_different_run_id_are_not_delivered(self) -> None:
        broker = LiveEventBroker()
        run_id = uuid4()
        other_run_id = uuid4()
        generator = _stream_events(broker, run_id, poll_interval_seconds=0.05)

        pending_chunk = asyncio.ensure_future(generator.__anext__())
        await asyncio.sleep(0)
        broker.publish(str(other_run_id), {"event": "investigation.tool.call_completed"})

        chunk = await asyncio.wait_for(pending_chunk, timeout=1)
        self.assertEqual(chunk, ": keep-alive\n\n")

        await generator.aclose()


if __name__ == "__main__":
    unittest.main()
