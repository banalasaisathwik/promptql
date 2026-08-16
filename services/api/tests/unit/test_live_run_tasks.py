import asyncio
import unittest

from app.runtime.live_run_tasks import LiveRunTaskRegistry


class LiveRunTaskRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_runs_a_scheduled_operation_to_completion(self) -> None:
        registry = LiveRunTaskRegistry()
        completed = asyncio.Event()

        async def operation() -> None:
            await asyncio.sleep(0)
            completed.set()

        registry.start(operation())
        await asyncio.wait_for(completed.wait(), timeout=1)
        await registry.shutdown()

        self.assertTrue(completed.is_set())

    async def test_shutdown_cancels_an_unfinished_in_process_task(self) -> None:
        registry = LiveRunTaskRegistry()
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def unfinished_operation() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        registry.start(unfinished_operation())
        await asyncio.wait_for(started.wait(), timeout=1)

        await registry.shutdown()

        self.assertTrue(cancelled.is_set())


if __name__ == "__main__":
    unittest.main()
