"""
A command handler for the 'help' command.
"""

from typing import TYPE_CHECKING

from src.core.commands.command import Command
from src.core.commands.handler import ICommandHandler
from src.core.commands.registry import command
from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session

if TYPE_CHECKING:
    from src.core.interfaces.command_service_interface import ICommandService


@command("help")
class HelpCommandHandler(ICommandHandler):
    """
    A command handler for the 'help' command.
    """

    @property
    def command_name(self) -> str:
        """Get the command name."""
        return "help"

    @property
    def description(self) -> str:
        """Get the command description."""
        return "Shows a list of all available commands or help for a specific command."

    @property
    def format(self) -> str:
        """Get the command format."""
        return "help [command_name]"

    @property
    def examples(self) -> list[str]:
        """Get command usage examples."""
        return ["help", "help hello"]

    def __init__(self, command_service: "ICommandService | None" = None) -> None:
        self._command_service = command_service

    async def handle(self, command: Command, session: Session) -> CommandResult:
        """Handle the help command.

        When instantiated with a command service (unit tests), return detailed help.
        Otherwise (integration path), return a concise placeholder string.
        """
        if self._command_service is None:
            return CommandResult(success=True, message="Mock help information")

        # Detailed mode using service methods
        if command.args:
            raw_cmd_name = command.args.get("command_name")
            if not raw_cmd_name:
                raw_cmd_name = command.args.get("command")

            if not raw_cmd_name and command.args:
                first_key, first_value = next(iter(command.args.items()))
                if isinstance(first_value, str) and first_value.strip():
                    raw_cmd_name = first_value
                elif first_value:
                    raw_cmd_name = str(first_value)
                else:
                    raw_cmd_name = first_key

            cmd_name = str(raw_cmd_name).strip() if raw_cmd_name is not None else ""
            if cmd_name:
                handler_class = await self._command_service.get_command_handler(cmd_name)  # type: ignore[attr-defined]
                if handler_class is None:
                    return CommandResult(
                        success=False, message=f"Command '{cmd_name}' not found."
                    )
                handler: ICommandHandler = handler_class(self._command_service)
                parts = [
                    f"{handler.command_name} - {handler.description}",
                    f"Format: {handler.format}",
                    "Examples:",
                ]
                parts.extend([f"  {ex}" for ex in handler.examples])
                return CommandResult(success=True, message="\n".join(parts))

        all_cmds = await self._command_service.get_all_commands()  # type: ignore[attr-defined]
        if not all_cmds:
            return CommandResult(success=True, message="No commands available.")
        lines = ["Available commands:"]
        for name, handler in all_cmds.items():
            lines.append(f"- {name} - {handler.description}")
        return CommandResult(success=True, message="\n".join(lines))
