"""Compatibility shim providing legacy SetCommandHandler expected by tests.

This handler implements a minimal subset of the legacy behaviour required by
unit tests: handling `temperature` parameter and mutating the provided
`SessionStateAdapter` (proxy_state) in-place.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.commands.handlers.base_handler import (
    BaseCommandHandler,
    CommandHandlerResult,
)
from src.core.domain.command_context import CommandContext
from src.core.interfaces.domain_entities_interface import ISessionState

logger = logging.getLogger(__name__)


class SetCommandHandler(BaseCommandHandler):
    """Minimal Set command handler compatibility shim."""

    def __init__(self) -> None:
        super().__init__("set")

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle legacy set parameters.

        This is a minimal compatibility shim that only handles temperature setting
        as required by existing unit tests.

        Args:
            param_value: The parameter value to set
            current_state: The current session state
            context: Optional command context

        Returns:
            Command handler result
        """
        if not param_value:
            return CommandHandlerResult(
                success=False,
                message="No parameters specified",
            )

        # Handle temperature parameter
        if isinstance(param_value, list) and len(param_value) > 0:
            # Parse key=value format
            try:
                param_str = param_value[0]
                if "=" in param_str:
                    key, value = param_str.split("=", 1)
                    key = key.strip().lower()
                    value = value.strip()

                    if key == "temperature":
                        try:
                            temp_value = float(value)
                            if temp_value < 0.0 or temp_value > 1.0:
                                return CommandHandlerResult(
                                    success=False,
                                    message="Invalid temperature value. Must be between 0.0 and 1.0",
                                )

                            # Update the temperature in the reasoning config
                            if (
                                hasattr(current_state, "reasoning_config")
                                and current_state.reasoning_config
                            ):
                                # Create a new reasoning config with updated temperature
                                new_reasoning_config = (
                                    current_state.reasoning_config.with_temperature(
                                        temp_value
                                    )
                                )

                                # Update the current state with the new reasoning config
                                new_state = current_state.with_reasoning_config(
                                    new_reasoning_config
                                )

                                return CommandHandlerResult(
                                    success=True,
                                    message=f"Temperature set to {temp_value}",
                                    new_state=new_state,
                                )
                            else:
                                return CommandHandlerResult(
                                    success=False,
                                    message="Reasoning configuration not available",
                                )
                        except ValueError:
                            return CommandHandlerResult(
                                success=False,
                                message="Invalid temperature value. Must be a number between 0.0 and 1.0",
                            )
                    else:
                        return CommandHandlerResult(
                            success=False,
                            message=f"Unsupported parameter: {key}",
                        )
                else:
                    return CommandHandlerResult(
                        success=False,
                        message="Invalid format. Use key=value format",
                    )
            except Exception as e:
                logger.error(f"Error processing parameter: {e}")
                return CommandHandlerResult(
                    success=False,
                    message=f"Error processing parameter: {e}",
                )
        else:
            return CommandHandlerResult(
                success=False,
                message="Invalid parameter format",
            )
