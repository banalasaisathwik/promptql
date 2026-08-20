class UnknownToolError(LookupError):
    def __init__(self, tool_id: str) -> None:
        self.tool_id = tool_id
        super().__init__(f"unknown investigation tool: {tool_id}")


class DuplicateToolError(ValueError):
    def __init__(self, tool_id: str) -> None:
        self.tool_id = tool_id
        super().__init__(f"investigation tool is already registered: {tool_id}")


class InvalidToolArgumentsError(ValueError):
    def __init__(self, tool_id: str) -> None:
        self.tool_id = tool_id
        super().__init__(f"invalid arguments for investigation tool: {tool_id}")
