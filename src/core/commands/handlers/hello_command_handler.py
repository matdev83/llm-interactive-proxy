"""
A command handler for the 'hello' command.
"""

from typing import TYPE_CHECKING

from src.core.commands.command import Command
from src.core.commands.handler import ICommandHandler
from src.core.commands.registry import command
from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session

if TYPE_CHECKING:
    from src.core.interfaces.command_service_interface import ICommandService


@command("hello")
class HelloCommandHandler(ICommandHandler):
    """
    A command handler for the 'hello' command.
    """

    def __init__(self, command_service: "ICommandService | None" = None) -> None:
        super().__init__(command_service)

    @property
    def command_name(self) -> str:
        """Get the command name."""
        return "hello"

    @property
    def description(self) -> str:
        """Get the command description."""
        return "Greets the user."

    @property
    def format(self) -> str:
        """Get the command format."""
        return "hello"

    @property
    def examples(self) -> list[str]:
        """Get command usage examples."""
        return ["hello"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        """Handle the hello command."""
        session.state.hello_requested = True
        message = (
            "Welcome to LLM Interactive Proxy!\n\n"
            "Available commands:\n"
            "- !/help - Show help information\n"
            "- !/set(param=value) - Set a parameter value\n"
            "- !/unset(param) - Unset a parameter value"
        )
        return CommandResult(success=True, message=message, new_state=session.state)
