from collections.abc import Iterable

from app.tools.errors import DuplicateToolError, UnknownToolError
from app.tools.models import ToolDefinition


class ToolRegistry:
    def __init__(self, definitions: Iterable[ToolDefinition] = ()) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: ToolDefinition) -> None:
        if definition.tool_id in self._definitions:
            raise DuplicateToolError(definition.tool_id)
        self._definitions[definition.tool_id] = definition

    def get(self, tool_id: str) -> ToolDefinition:
        try:
            return self._definitions[tool_id]
        except KeyError:
            raise UnknownToolError(tool_id) from None

    def list(self) -> tuple[ToolDefinition, ...]:
        return tuple(
            self._definitions[tool_id]
            for tool_id in sorted(self._definitions)
        )
