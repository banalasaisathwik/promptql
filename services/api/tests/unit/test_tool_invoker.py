import asyncio
import unittest

from app.investigations.baseline import ToolInvoker
from app.tools import (
    TOOL_DEFINITIONS,
    InvestigationToolId,
    ToolFailureCode,
    ToolOutcome,
    ToolRegistry,
    ToolResult,
)


def _definition_with(tool_id: InvestigationToolId, **overrides: object):
    base = next(item for item in TOOL_DEFINITIONS if item.tool_id == tool_id)
    return base.model_copy(update=overrides)


class _RecordingTool:
    def __init__(self, definition, handler) -> None:
        self.definition = definition
        self.calls = 0
        self._handler = handler

    async def execute(self, arguments):
        self.calls += 1
        return await self._handler(arguments)


class ToolInvokerWriteCapabilityTests(unittest.IsolatedAsyncioTestCase):
    """Covers the read_only enforcement gate added to ToolInvoker.invoke.

    All 8 registered tools are read_only=True today, so this exercises a
    locally constructed write-capable definition rather than a real tool_id.
    """

    def setUp(self) -> None:
        self.definition = _definition_with(InvestigationToolId.GET_INCIDENT, read_only=False)

    def _tool(self):
        async def handler(arguments):
            return ToolResult(
                tool_id=self.definition.tool_id,
                outcome=ToolOutcome.OBSERVED,
                evidence_ids=("incident:1",),
            )

        return _RecordingTool(self.definition, handler)

    async def test_write_tool_rejected_without_opt_in(self) -> None:
        tool = self._tool()
        invoker = ToolInvoker(ToolRegistry([self.definition]), {self.definition.tool_id: tool})

        result = await invoker.invoke(self.definition.tool_id, {})

        self.assertEqual(result.outcome, ToolOutcome.FAILED)
        self.assertEqual(result.failure.code, ToolFailureCode.WRITE_CAPABILITY_NOT_GRANTED)
        self.assertFalse(result.failure.retryable)
        self.assertEqual(tool.calls, 0)

    async def test_write_tool_accepted_with_opt_in(self) -> None:
        tool = self._tool()
        invoker = ToolInvoker(
            ToolRegistry([self.definition]),
            {self.definition.tool_id: tool},
            allow_write_tools=True,
        )

        result = await invoker.invoke(self.definition.tool_id, {})

        self.assertEqual(result.outcome, ToolOutcome.OBSERVED)
        self.assertEqual(tool.calls, 1)

    async def test_read_only_tools_are_unaffected_by_the_gate(self) -> None:
        read_only_definition = _definition_with(InvestigationToolId.GET_INCIDENT)

        async def handler(arguments):
            return ToolResult(
                tool_id=read_only_definition.tool_id,
                outcome=ToolOutcome.OBSERVED,
                evidence_ids=("incident:1",),
            )

        tool = _RecordingTool(read_only_definition, handler)
        invoker = ToolInvoker(ToolRegistry([read_only_definition]), {read_only_definition.tool_id: tool})

        result = await invoker.invoke(read_only_definition.tool_id, {})

        self.assertEqual(result.outcome, ToolOutcome.OBSERVED)
        self.assertEqual(tool.calls, 1)


class ToolInvokerTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_produces_typed_timeout_failure_not_an_unhandled_exception(self) -> None:
        definition = _definition_with(InvestigationToolId.GET_INCIDENT, timeout_seconds=0.01)

        async def hang(arguments):
            await asyncio.sleep(10)
            raise AssertionError("execution should have been cancelled by the timeout")

        tool = _RecordingTool(definition, hang)
        invoker = ToolInvoker(ToolRegistry([definition]), {definition.tool_id: tool})

        result = await invoker.invoke(definition.tool_id, {})

        self.assertEqual(result.outcome, ToolOutcome.FAILED)
        self.assertEqual(result.failure.code, ToolFailureCode.TIMEOUT)
        self.assertTrue(result.failure.retryable)

    async def test_no_timeout_configured_runs_to_completion(self) -> None:
        definition = _definition_with(InvestigationToolId.GET_INCIDENT)
        self.assertIsNone(definition.timeout_seconds)

        async def fast(arguments):
            return ToolResult(
                tool_id=definition.tool_id,
                outcome=ToolOutcome.OBSERVED,
                evidence_ids=("incident:1",),
            )

        tool = _RecordingTool(definition, fast)
        invoker = ToolInvoker(ToolRegistry([definition]), {definition.tool_id: tool})

        result = await invoker.invoke(definition.tool_id, {})

        self.assertEqual(result.outcome, ToolOutcome.OBSERVED)


if __name__ == "__main__":
    unittest.main()
