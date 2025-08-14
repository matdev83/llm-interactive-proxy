from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .base import BaseCommand, CommandResult, register_command

if TYPE_CHECKING:
    from src.proxy_logic import ProxyState


@register_command
class PwdCommand(BaseCommand):
    name = "pwd"
    format = "pwd"
    description = "Print the current project directory."
    examples = ["!/pwd"]

    def execute(self, args: Mapping[str, Any], state: ProxyState) -> CommandResult:
        if state.project_dir:
            return CommandResult(self.name, True, state.project_dir)
        else:
            return CommandResult(self.name, False, "Project directory not set.")
