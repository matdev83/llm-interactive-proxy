"""Compatibility shim providing legacy SetCommandHandler expected by tests.

This handler implements a minimal subset of the legacy behaviour required by
unit tests: handling `temperature` and `command-prefix` parameters and mutating 
the provided `SessionStateAdapter` (proxy_state) in-place.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from src.core.commands.handlers.base_handler import (
    BaseCommandHandler,
    CommandHandlerResult,
)
from src.core.constants import COMMAND_PARSING_ERROR
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
                    elif key == "command-prefix":
                        # Validate command prefix
                        from src.command_prefix import validate_command_prefix
                        
                        error = validate_command_prefix(value)
                        if error:
                            return CommandHandlerResult(
                                success=False,
                                message=error,
                            )
                        
                        # Update command prefix in application state
                        if context and hasattr(context, "app") and hasattr(context.app, "state"):
                            context.app.state.command_prefix = value
                            
                        # Also update in session state if available
                        from src.core.domain.session import SessionStateAdapter
                        
                        if isinstance(current_state, SessionStateAdapter) and hasattr(current_state, "_state"):
                            # No direct setter for command_prefix in SessionState
                            # Return success and let the command processor handle it
                            return CommandHandlerResult(
                                success=True,
                                message=f"Command prefix set to {value}",
                                new_state=current_state,  # Return current state unchanged
                            )
                        
                        return CommandHandlerResult(
                            success=True,
                            message=f"Command prefix set to {value}",
                        )
                    elif key == "interactive-mode":
                        # Handle interactive mode setting
                        value_upper = value.upper()
                        if value_upper in ("ON", "TRUE", "YES", "1", "ENABLED", "ENABLE"):
                            enabled = True
                        elif value_upper in ("OFF", "FALSE", "NO", "0", "DISABLED", "DISABLE"):
                            enabled = False
                        else:
                            return CommandHandlerResult(
                                success=False,
                                message=f"Invalid interactive mode value: {value}. Use ON/OFF, TRUE/FALSE, etc.",
                            )
                        
                        # Update interactive mode in session state
                        from src.core.domain.session import SessionStateAdapter
                        
                        if isinstance(current_state, SessionStateAdapter) and hasattr(current_state, "_state"):
                            # Use the with_interactive_just_enabled method to create a new state
                            
                            # Use the interface method to create a new state with updated flag
                            updated_state = current_state.with_interactive_just_enabled(enabled)
                            
                            # For immediate effect in tests, we also need to update the adapter directly
                            # This is a compatibility shim for tests that expect immediate state changes
                            if hasattr(current_state, "interactive_just_enabled") and hasattr(type(current_state), "interactive_just_enabled"):
                                prop = type(current_state).interactive_just_enabled
                                if hasattr(prop, "fset") and prop.fset is not None:
                                    # Only set if it has a setter
                                    # Use contextlib.suppress to avoid noisy try/except-pass
                                    with contextlib.suppress(Exception):
                                        current_state.interactive_just_enabled = enabled  # type: ignore[misc]
                            
                            return CommandHandlerResult(
                                success=True,
                                message=f"Interactive mode {'enabled' if enabled else 'disabled'}",
                                new_state=updated_state,
                            )
                        
                        # Fallback for other state types
                        if hasattr(current_state, "with_interactive_just_enabled"):
                            updated_state = current_state.with_interactive_just_enabled(enabled)
                            return CommandHandlerResult(
                                success=True,
                                message=f"Interactive mode {'enabled' if enabled else 'disabled'}",
                                new_state=updated_state,
                            )
                        
                        return CommandHandlerResult(
                            success=False,
                            message="Cannot update interactive mode: unsupported state type",
                        )
                    else:
                        return CommandHandlerResult(
                            success=False,
                            message=f"Unknown parameter: {key}",
                        )
                else:
                    return CommandHandlerResult(
                        success=False,
                        message="Invalid format. Use key=value format",
                    )
            except Exception as e:
                error_message = COMMAND_PARSING_ERROR.format(error=str(e))
                logger.error(error_message)
                return CommandHandlerResult(
                    success=False,
                    message=error_message,
                )
        else:
            return CommandHandlerResult(
                success=False,
                message="Invalid parameter format",
            )
