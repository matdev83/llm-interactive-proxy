"""
A command handler for the 'tool-loop-max-repeats' command.
"""

from typing import TYPE_CHECKING

from src.core.commands.command import Command
from src.core.commands.handler import ICommandHandler
from src.core.commands.registry import command
from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session

if TYPE_CHECKING:
    from src.core.interfaces.command_service_interface import ICommandService


@command("tool-loop-max-repeats")
class ToolLoopMaxRepeatsCommandHandler(ICommandHandler):
    """
    A command handler for the 'tool-loop-max-repeats' command.
    """

    def __init__(self, command_service: "ICommandService | None" = None) -> None:
        super().__init__(command_service)

    @property
    def command_name(self) -> str:
        """Get the command name."""
        return "tool-loop-max-repeats"

    @property
    def description(self) -> str:
        """Get the command description."""
        return "Set the maximum number of repeats for tool loop detection."

    @property
    def format(self) -> str:
        """Get the command format."""
        return "tool-loop-max-repeats <value>"

    @property
    def examples(self) -> list[str]:
        """Get command usage examples."""
        return ["tool-loop-max-repeats 5"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        """Handle the tool-loop-max-repeats command."""
        if not command.args:
            return CommandResult(
                success=False, message="Error: Please provide a value for max repeats."
            )

        max_repeats_str = next(iter(command.args.values()), None)
        if max_repeats_str is None:
            return CommandResult(
                success=False, message="Error: Please provide a value for max repeats."
            )

        try:
            max_repeats = int(max_repeats_str)
            if max_repeats < 1:
                return CommandResult(
                    success=False,
                    message="Error: Max repeats must be a positive integer.",
                )

            new_config = session.state.loop_config.with_tool_loop_max_repeats(
                max_repeats
            )
            session.state = session.state.with_loop_config(new_config)
            return CommandResult(
                success=True,
                message=f"Tool loop max repeats set to {max_repeats}.",
                new_state=session.state,
            )
        except ValueError:
            return CommandResult(
                success=False, message="Error: Max repeats must be a valid integer."
            )
