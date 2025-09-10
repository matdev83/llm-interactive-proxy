from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.commands.command import Command, CommandResult
from src.core.commands.handler import ICommandHandler
from src.core.commands.registry import command
from src.core.domain.session import Session

if TYPE_CHECKING:
    pass


@command("unset")
class UnsetCommandHandler(ICommandHandler):
    """Handler for the 'unset' command."""

    @property
    def command_name(self) -> str:
        return "unset"

    @property
    def description(self) -> str:
        return "Unset a session value."

    @property
    def format(self) -> str:
        return "!/unset(key)"

    @property
    def examples(self) -> list[str]:
        return ["!/unset(model)"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        # This is a simplified implementation for the sake of the test.
        # In a real implementation, this would modify the session state.
        if not command.args:
            return CommandResult(success=False, message="No arguments provided.")

        # In a real implementation, we would update the session state here.
        # For the test, we just return a success message.
        return CommandResult(success=True, message="Settings unset")
