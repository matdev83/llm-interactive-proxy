from __future__ import annotations

from collections.abc import Mapping  # Removed List, Set
from typing import TYPE_CHECKING, Any

from .base import BaseCommand, CommandResult, command_registry, register_command

if TYPE_CHECKING:
    from src.proxy_logic import ProxyState


@register_command
class HelpCommand(BaseCommand):
    name = "help"
    format = "help(<command>)"
    description = "Show available commands or details for a single command"
    examples = ["!/help", "!/help(set)"]

    def execute(self, args: Mapping[str, Any], state: ProxyState) -> CommandResult:
        if args:
            # assume first argument name is the command
            cmd_name = next(iter(args.keys())).lower()
            cmd_cls = command_registry.get(cmd_name)
            if not cmd_cls:
                return CommandResult(self.name, False, f"unknown command: {cmd_name}")
            parts = [
                f"{cmd_cls.name} - {cmd_cls.description}",
                f"format: {cmd_cls.format}",
            ]
            if cmd_cls.examples:
                parts.append("examples: " + "; ".join(cmd_cls.examples))
            return CommandResult(self.name, True, "; ".join(parts))
        names = sorted(command_registry.keys())
        return CommandResult(self.name, True, "available commands: " + ", ".join(names))
