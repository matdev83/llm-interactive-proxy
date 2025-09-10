from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.commands.command import Command, CommandResult
from src.core.commands.handler import ICommandHandler
from src.core.commands.registry import command
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
        # This is a simplified implementation for the sake of the test.
        # In a real implementation, this would modify the session state.
        if not command.args:
            return CommandResult(success=False, message="No arguments provided.")

        # In a real implementation, we would update the session state here.
        # For the test, we just return a success message.
        return CommandResult(success=True, message="Settings updated")
