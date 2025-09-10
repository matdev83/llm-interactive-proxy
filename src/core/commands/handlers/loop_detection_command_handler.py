"""
A command handler for the 'loop-detection' command.
"""

from src.core.commands.command import Command, CommandResult
from src.core.commands.handler import ICommandHandler
from src.core.commands.registry import command
from src.core.domain.session import Session


@command("tool-loop-detection")
class LoopDetectionCommandHandler(ICommandHandler):
    """
    A command handler for the 'loop-detection' command.
    """

    @property
    def command_name(self) -> str:
        """Get the command name."""
        return "tool-loop-detection"

    @property
    def description(self) -> str:
        """Get the command description."""
        return "Enable or disable tool loop detection."

    @property
    def format(self) -> str:
        """Get the command format."""
        return "tool-loop-detection <true|false>"

    @property
    def examples(self) -> list[str]:
        """Get command usage examples."""
        return ["tool-loop-detection true", "tool-loop-detection false"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        """Handle the loop-detection command."""
        if not command.args:
            return CommandResult(
                success=False, message="Error: Please provide a value (true/false)."
            )

        enabled_str = next(iter(command.args.values()), "").lower()
        if enabled_str not in ["true", "false"]:
            return CommandResult(
                success=False,
                message="Error: Invalid value. Please use 'true' or 'false'.",
            )

        enabled = enabled_str == "true"
        new_config = session.state.loop_config.with_tool_loop_detection_enabled(enabled)
        session.state = session.state.with_loop_config(new_config)

        return CommandResult(
            success=True,
            message=f"Tool loop detection set to {enabled}.",
            new_state=session.state,
        )
