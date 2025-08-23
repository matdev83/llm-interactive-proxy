from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.secure_base_command import StatelessCommandBase
from src.core.domain.session import Session

logger = logging.getLogger(__name__)


class LoopDetectionCommand(StatelessCommandBase, BaseCommand):
    """Command for enabling/disabling loop detection."""

    def __init__(self) -> None:
        """Initialize without state services."""
        StatelessCommandBase.__init__(self)

    @property
    def name(self) -> str:
        return "loop-detection"

    @property
    def format(self) -> str:
        return "loop-detection(enabled=true|false)"

    @property
    def description(self) -> str:
        return "Enable or disable loop detection for the current session"

    @property
    def examples(self) -> list[str]:
        return ["!/loop-detection(enabled=true)", "!/loop-detection(enabled=false)"]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Enable or disable loop detection."""
        # Defaults to enabled=True if no value is provided, e.g., !/loop-detection()
        enabled_arg = args.get("enabled", "true")
        enabled = str(enabled_arg).lower() in ("true", "yes", "1", "on")

        try:
            loop_config = session.state.loop_config.with_loop_detection_enabled(enabled)
            updated_state = session.state.with_loop_config(loop_config)

            return CommandResult(
                name=self.name,
                success=True,
                message=f"Loop detection {'enabled' if enabled else 'disabled'}",
                data={"enabled": enabled},
                new_state=updated_state,
            )
        except Exception as e:
            logger.error(f"Error toggling loop detection: {e}")
            return CommandResult(
                success=False,
                message=f"Error toggling loop detection: {e}",
                name=self.name,
            )
