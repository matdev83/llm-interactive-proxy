import json
from typing import Any


class CommandBuilder:
    def __init__(self) -> None:
        self._command: dict[str, Any] = {
            "tool_name": "execute_command",
            "arguments": "{}",
        }

    def with_command(self, command: str) -> "CommandBuilder":
        self._command["tool_name"] = command
        return self

    def with_arguments(self, **kwargs: Any) -> "CommandBuilder":
        self._command["arguments"] = json.dumps(kwargs)
        return self

    def build(self) -> dict[str, Any]:
        return self._command
