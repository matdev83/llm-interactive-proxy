"""Command handler for setting the tool loop TTL (time-to-live) seconds."""

from typing import TYPE_CHECKING

from src.core.commands.command import Command
from src.core.commands.handler import ICommandHandler
from src.core.commands.registry import command
from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session

if TYPE_CHECKING:
    from src.core.interfaces.command_service_interface import ICommandService


@command("tool-loop-ttl")
class ToolLoopTtlCommandHandler(ICommandHandler):
    """Handler for the tool-loop-ttl command."""

    def __init__(self, command_service: "ICommandService | None" = None):
        """Initialize the handler with a command service."""
        super().__init__(command_service)

    @property
    def command_name(self) -> str:
        """Get the command name."""
        return "tool-loop-ttl"

    @property
    def description(self) -> str:
        """Get the command description."""
        return "Set the tool call loop TTL (time-to-live) in seconds"

    @property
    def format(self) -> str:
        """Get the command format."""
        return "tool-loop-ttl <seconds>"

    @property
    def examples(self) -> list[str]:
        """Get command usage examples."""
        return [
            "tool-loop-ttl 300  # Set TTL to 5 minutes",
            "tool-loop-ttl 3600 # Set TTL to 1 hour",
        ]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        """Handle the tool-loop-ttl command.

        Args:
            command: The command to handle.
            session: The current session.

        Returns:
            A string with the result of the command.
        """
        if not command.args:
            return CommandResult(
                success=False, message="Error: Please provide the TTL seconds value."
            )

        ttl_seconds_str = next(iter(command.args.values()), None)
        if ttl_seconds_str is None:
            return CommandResult(
                success=False, message="Error: Please provide the TTL seconds value."
            )

        try:
            ttl_seconds = int(ttl_seconds_str)
        except ValueError:
            return CommandResult(
                success=False, message="Error: TTL seconds must be a valid integer."
            )

        if ttl_seconds < 1:
            return CommandResult(
                success=False, message="Error: TTL seconds must be at least 1."
            )

        new_config = session.state.loop_config.with_tool_loop_ttl_seconds(ttl_seconds)
        session.state = session.state.with_loop_config(new_config)

        return CommandResult(
            success=True,
            message=f"Tool call loop TTL set to {ttl_seconds} seconds.",
            new_state=session.state,
        )
