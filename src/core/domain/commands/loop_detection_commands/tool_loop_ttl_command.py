from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session

logger = logging.getLogger(__name__)

class ToolLoopTTLCommand(BaseCommand):
    """Command for setting tool loop TTL."""

    name = "tool-loop-ttl"
    format = "tool-loop-ttl(ttl_seconds=<number>)"
    description = "Set the TTL (time to live) for tool loop detection in seconds"
    examples = ["!/tool-loop-ttl(ttl_seconds=60)"]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Set tool loop TTL."""
        ttl_seconds_arg = args.get("ttl_seconds")

        if ttl_seconds_arg is None:
            return CommandResult(success=False, message="TTL seconds must be specified", name=self.name)

        try:
            ttl_seconds_int = int(ttl_seconds_arg)
            if ttl_seconds_int < 1:
                return CommandResult(success=False, message="TTL seconds must be at least 1", name=self.name)
        except (ValueError, TypeError):
            return CommandResult(success=False, message="TTL seconds must be a valid integer", name=self.name)

        try:
            loop_config = session.state.loop_config.with_tool_loop_ttl_seconds(ttl_seconds_int)
            updated_state = session.state.with_loop_config(loop_config)

            return CommandResult(
                name=self.name,
                success=True,
                message=f"Tool loop TTL set to {ttl_seconds_int} seconds",
                data={"ttl_seconds": ttl_seconds_int},
                new_state=updated_state,
            )
        except Exception as e:
            logger.error(f"Error setting tool loop TTL: {e}")
            return CommandResult(
                success=False, message=f"Error setting tool loop TTL: {e}", name=self.name
            )