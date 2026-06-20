"""
Loop detection setting handlers for the SOLID architecture.

This module provides command handlers for generic reply/content loop detection.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.commands.handlers.base_handler import (
    BaseCommandHandler,
    CommandHandlerResult,
)
from src.core.constants.command_output_constants import (
    LOOP_DETECTION_BOOLEAN_REQUIRED_MESSAGE,
    LOOP_DETECTION_DISABLED_MESSAGE,
    LOOP_DETECTION_ENABLED_MESSAGE,
    LOOP_DETECTION_INVALID_BOOLEAN_MESSAGE,
)
from src.core.domain.command_context import CommandContext
from src.core.interfaces.domain_entities_interface import ISessionState

logger = logging.getLogger(__name__)


class LoopDetectionHandler(BaseCommandHandler):
    """Handler for enabling/disabling generic reply/content loop detection."""

    def __init__(self) -> None:
        """Initialize the loop detection handler."""
        super().__init__("loop-detection")

    @property
    def aliases(self) -> list[str]:
        """Aliases for the parameter name."""
        return ["loop_detection"]

    @property
    def description(self) -> str:
        """Description of the command."""
        return "Enable or disable loop detection"

    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return ["~/set(loop-detection=true)", "~/set(loop-detection=false)"]

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter."""
        normalized = param_name.lower().replace("_", "-").replace(" ", "-")
        return normalized == self.name or normalized in [
            a.lower() for a in self.aliases
        ]

    def _parse_bool(self, value: str) -> bool | None:
        """Parse a boolean value from a string."""
        val = value.strip().lower()
        if val in ("true", "1", "yes", "on"):
            return True
        if val in ("false", "0", "no", "off", "none"):
            return False
        return None

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle enabling/disabling generic reply/content loop detection."""
        if param_value is None:
            return CommandHandlerResult(
                success=False, message=LOOP_DETECTION_BOOLEAN_REQUIRED_MESSAGE
            )

        bool_value = self._parse_bool(str(param_value))
        if bool_value is None:
            return CommandHandlerResult(
                success=False,
                message=LOOP_DETECTION_INVALID_BOOLEAN_MESSAGE.format(
                    value=param_value
                ),
            )

        new_state = current_state.with_loop_config(
            current_state.loop_config.with_loop_detection_enabled(bool_value)
        )

        return CommandHandlerResult(
            success=True,
            message=(
                LOOP_DETECTION_ENABLED_MESSAGE
                if bool_value
                else LOOP_DETECTION_DISABLED_MESSAGE
            ),
            new_state=new_state,
        )
