from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from src.core.commands.command import Command
from src.core.commands.handler import ICommandHandler
from src.core.commands.registry import command
from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session

if TYPE_CHECKING:
    pass


@command("set")
class SetCommandHandler(ICommandHandler):
    """Handler for the 'set' command."""

    @property
    def command_name(self) -> str:
        return "set"

    @property
    def description(self) -> str:
        return "Set a session value."

    @property
    def format(self) -> str:
        return "!/set(key=value)"

    @property
    def examples(self) -> list[str]:
        return ["!/set(model=anthropic/claude-3-opus-20240229)"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        """Handle set command by updating session state for supported keys."""
        if not command.args:
            return CommandResult(success=False, message="No arguments provided.")

        # Update backend provider and/or model when specified
        backend = command.args.get("backend")
        model = command.args.get("model")

        if isinstance(backend, str) and backend:
            with contextlib.suppress(Exception):
                session.set_provider(backend)

        if isinstance(model, str) and model:
            with contextlib.suppress(Exception):
                session.set_model(model)

        return CommandResult(success=True, message="Settings updated")
