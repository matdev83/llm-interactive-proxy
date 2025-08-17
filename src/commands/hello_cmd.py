from __future__ import annotations

from collections.abc import Mapping  # Removed List, Set
from typing import TYPE_CHECKING, Any

from .base import BaseCommand, CommandResult, register_command

if TYPE_CHECKING:
    pass  # No imports needed


@register_command
class HelloCommand(BaseCommand):
    name = "hello"
    format = "hello"
    description = "Return the interactive welcome banner"
    examples = ["!/hello"]

    def execute(self, args: Mapping[str, Any], state: Any) -> CommandResult:
        state.hello_requested = True
        return CommandResult(self.name, True, "hello acknowledged")
