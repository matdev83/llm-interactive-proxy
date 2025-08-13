from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping  # Removed List, Set

from .base import BaseCommand, CommandResult, register_command

if TYPE_CHECKING:
    from src.proxy_logic import ProxyState


@register_command
class HelloCommand(BaseCommand):
    name = "hello"
    format = "hello"
    description = "Return the interactive welcome banner"
    examples = ["!/hello"]

    def execute(self, args: Mapping[str, Any], state: ProxyState) -> CommandResult:
        state.hello_requested = True
        return CommandResult(self.name, True, "hello acknowledged")
