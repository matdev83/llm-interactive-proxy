"""
A command handler for the 'tool-loop-mode' command.
"""

from typing import TYPE_CHECKING

from src.core.commands.command import Command, CommandResult
from src.core.commands.handler import ICommandHandler
from src.core.commands.registry import command
from src.core.domain.session import Session
from src.tool_call_loop.config import ToolLoopMode

if TYPE_CHECKING:
    from src.core.interfaces.command_service_interface import ICommandService


@command("tool-loop-mode")
class ToolLoopModeCommandHandler(ICommandHandler):
    """
    A command handler for the 'tool-loop-mode' command.
    """

    def __init__(self, command_service: "ICommandService | None" = None) -> None:
        super().__init__(command_service)

    @property
    def command_name(self) -> str:
        """Get the command name."""
        return "tool-loop-mode"

    @property
    def description(self) -> str:
        """Get the command description."""
        return "Set the mode for tool loop detection."

    @property
    def format(self) -> str:
        """Get the command format."""
        valid_modes = ", ".join([m.value for m in ToolLoopMode])
        return f"tool-loop-mode <{valid_modes}>"

    @property
    def examples(self) -> list[str]:
        """Get command usage examples."""
        return ["tool-loop-mode none", "tool-loop-mode simple"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        """Handle the tool-loop-mode command."""
        if not command.args:
            return CommandResult(success=False, message="Error: Please provide a mode.")

        mode_str = next(iter(command.args.values()), None)
        if mode_str is None:
            return CommandResult(success=False, message="Error: Please provide a mode.")

        try:
            mode = ToolLoopMode(mode_str)
            new_config = session.state.loop_config.with_tool_loop_mode(mode)
            session.state = session.state.with_loop_config(new_config)
            return CommandResult(
                success=True,
                message=f"Tool loop mode set to {mode.value}.",
                new_state=session.state,
            )
        except ValueError:
            valid_modes = ", ".join([m.value for m in ToolLoopMode])
            return CommandResult(
                success=False,
                message=f"Invalid mode '{mode_str}'. Valid modes: {valid_modes}",
            )
