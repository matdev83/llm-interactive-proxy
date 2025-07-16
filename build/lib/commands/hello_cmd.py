from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict  # Removed List, Set

from .base import BaseCommand, CommandResult, register_command

if TYPE_CHECKING:
    from ..proxy_logic import ProxyState


@register_command
class HelloCommand(BaseCommand):
    name = "hello"
    format = "hello"
    description = "Return the interactive welcome banner"
    examples = ["!/hello"]

    def execute(self, args: Dict[str, Any],
                state: "ProxyState") -> CommandResult:
        state.hello_requested = True
        return CommandResult(self.name, True, "hello acknowledged")
