"""Command handlers for loop detection toggles."""

from src.core.commands.command import Command
from src.core.commands.handler import ICommandHandler
from src.core.commands.registry import command
from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session


def _parse_bool_argument(args: dict[str, object]) -> tuple[bool | None, str | None]:
    """Extract a boolean flag from command arguments."""

    if not args:
        return True, None

    enabled_arg = args.get("enabled")
    if enabled_arg is None:
        enabled_arg = next(iter(args.values()), None)

    if enabled_arg is None:
        return True, None

    normalized = str(enabled_arg).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True, None
    if normalized in {"false", "0", "no", "off"}:
        return False, None
    return None, normalized


@command("loop-detection")
class LoopDetectionCommandHandler(ICommandHandler):
    """Handler for the `/loop-detection` command."""

    @property
    def command_name(self) -> str:
        return "loop-detection"

    @property
    def description(self) -> str:
        return "Enable or disable loop detection."

    @property
    def format(self) -> str:
        return "loop-detection(enabled=true|false)"

    @property
    def examples(self) -> list[str]:
        return ["!/loop-detection(enabled=true)", "!/loop-detection(enabled=false)"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        enabled, invalid = _parse_bool_argument(command.args)
        if enabled is None:
            return CommandResult(
                success=False,
                message=(
                    "Error: Invalid value. Please use 'true' or 'false'."
                    if invalid is not None
                    else "Error: Please provide a value (true/false)."
                ),
            )

        new_config = session.state.loop_config.with_loop_detection_enabled(enabled)
        session.state = session.state.with_loop_config(new_config)

        return CommandResult(
            success=True,
            message=(
                "Loop detection enabled" if enabled else "Loop detection disabled"
            ),
            new_state=session.state,
        )


@command("tool-loop-detection")
class ToolLoopDetectionCommandHandler(ICommandHandler):
    """Handler for the `/tool-loop-detection` command."""

    @property
    def command_name(self) -> str:
        return "tool-loop-detection"

    @property
    def description(self) -> str:
        return "Enable or disable tool loop detection."

    @property
    def format(self) -> str:
        return "tool-loop-detection(enabled=true|false)"

    @property
    def examples(self) -> list[str]:
        return [
            "!/tool-loop-detection(enabled=true)",
            "!/tool-loop-detection(enabled=false)",
        ]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        enabled, invalid = _parse_bool_argument(command.args)
        if enabled is None:
            return CommandResult(
                success=False,
                message=(
                    "Error: Invalid value. Please use 'true' or 'false'."
                    if invalid is not None
                    else "Error: Please provide a value (true/false)."
                ),
            )

        new_config = session.state.loop_config.with_tool_loop_detection_enabled(
            enabled
        )
        session.state = session.state.with_loop_config(new_config)

        return CommandResult(
            success=True,
            message=(
                "Tool loop detection enabled"
                if enabled
                else "Tool loop detection disabled"
            ),
            new_state=session.state,
        )
