from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.secure_base_command import StatelessCommandBase
from src.core.domain.session import Session

logger = logging.getLogger(__name__)


class ToolLoopMaxRepeatsCommand(StatelessCommandBase, BaseCommand):
    """Command for setting tool loop max repeats."""

    def __init__(self):
        """Initialize without state services."""
        StatelessCommandBase.__init__(self)

    @property
    def name(self) -> str:
        return "tool-loop-max-repeats"

    @property
    def format(self) -> str:
        return "tool-loop-max-repeats(max_repeats=<number>)"

    @property
    def description(self) -> str:
        return "Set the maximum number of repeats for tool loop detection"

    @property
    def examples(self) -> list[str]:
        return ["!/tool-loop-max-repeats(max_repeats=5)"]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Set tool loop max repeats."""
        max_repeats_arg = args.get("max_repeats")

        if max_repeats_arg is None:
            return CommandResult(
                success=False, message="Max repeats must be specified", name=self.name
            )

        try:
            max_repeats_int = int(max_repeats_arg)
            if max_repeats_int < 2:
                return CommandResult(
                    success=False,
                    message="Max repeats must be at least 2",
                    name=self.name,
                )
        except (ValueError, TypeError):
            return CommandResult(
                success=False,
                message="Max repeats must be a valid integer",
                name=self.name,
            )

        try:
            loop_config = session.state.loop_config.with_tool_loop_max_repeats(
                max_repeats_int
            )
            updated_state = session.state.with_loop_config(loop_config)

            return CommandResult(
                name=self.name,
                success=True,
                message=f"Tool loop max repeats set to {max_repeats_int}",
                data={"max_repeats": max_repeats_int},
                new_state=updated_state,
            )
        except Exception as e:
            logger.error(f"Error setting tool loop max repeats: {e}")
            return CommandResult(
                success=False,
                message=f"Error setting tool loop max repeats: {e}",
                name=self.name,
            )
