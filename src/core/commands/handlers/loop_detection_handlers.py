"""
Loop detection setting handlers for the SOLID architecture.

This module provides command handlers for loop detection-related settings.
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
from src.tool_call_loop.config import ToolLoopMode

logger = logging.getLogger(__name__)


class LoopDetectionHandler(BaseCommandHandler):
    """Handler for enabling/disabling loop detection."""

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
        return [
            "!/set(loop-detection=true)",
            "!/set(loop-detection=false)",
        ]

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """
        normalized = param_name.lower().replace("_", "-").replace(" ", "-")
        return normalized == self.name or normalized in [
            a.lower() for a in self.aliases
        ]

    def _parse_bool(self, value: str) -> bool | None:
        """Parse a boolean value from a string.

        Args:
            value: The string to parse

        Returns:
            The parsed boolean value or None if parsing fails
        """
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
        """Handle enabling/disabling loop detection.

        Args:
            param_value: The boolean value
            current_state: The current session state
            context: Optional command context

        Returns:
            A result containing success/failure status and updated state
        """
        if param_value is None:
            return CommandHandlerResult(
                success=False, message="Boolean value must be specified"
            )

        bool_value = self._parse_bool(str(param_value))
        if bool_value is None:
            return CommandHandlerResult(
                success=False, message=f"Invalid boolean value: {param_value}"
            )

        # Create new state with updated loop detection setting
        new_state = current_state.with_loop_config(
            current_state.loop_config.with_loop_detection_enabled(bool_value)
        )

        return CommandHandlerResult(
            success=True,
            message=f"Loop detection {'enabled' if bool_value else 'disabled'}",
            new_state=new_state,
        )


class ToolLoopDetectionHandler(BaseCommandHandler):
    """Handler for enabling/disabling tool call loop detection."""

    def __init__(self) -> None:
        """Initialize the tool loop detection handler."""
        super().__init__("tool-loop-detection")

    @property
    def aliases(self) -> list[str]:
        """Aliases for the parameter name."""
        return ["tool_loop_detection"]

    @property
    def description(self) -> str:
        """Description of the command."""
        return "Enable or disable tool call loop detection"

    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return [
            "!/set(tool-loop-detection=true)",
            "!/set(tool-loop-detection=false)",
        ]

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """
        normalized = param_name.lower().replace("_", "-").replace(" ", "-")
        return normalized == self.name or normalized in [
            a.lower() for a in self.aliases
        ]

    def _parse_bool(self, value: str) -> bool | None:
        """Parse a boolean value from a string.

        Args:
            value: The string to parse

        Returns:
            The parsed boolean value or None if parsing fails
        """
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
        """Handle enabling/disabling tool call loop detection.

        Args:
            param_value: The boolean value
            current_state: The current session state
            context: Optional command context

        Returns:
            A result containing success/failure status and updated state
        """
        if param_value is None:
            return CommandHandlerResult(
                success=False, message="Boolean value must be specified"
            )

        bool_value = self._parse_bool(str(param_value))
        if bool_value is None:
            return CommandHandlerResult(
                success=False, message=f"Invalid boolean value: {param_value}"
            )

        # Create new state with updated tool loop detection setting
        new_state = current_state.with_loop_config(
            current_state.loop_config.with_tool_loop_detection_enabled(bool_value)
        )

        return CommandHandlerResult(
            success=True,
            message=f"Tool call loop detection {'enabled' if bool_value else 'disabled'}",
            new_state=new_state,
        )


class ToolLoopMaxRepeatsHandler(BaseCommandHandler):
    """Handler for setting the maximum number of tool call loop repetitions."""

    def __init__(self) -> None:
        """Initialize the tool loop max repeats handler."""
        super().__init__("tool-loop-max-repeats")

    @property
    def aliases(self) -> list[str]:
        """Aliases for the parameter name."""
        return ["tool_loop_max_repeats", "max_repeats"]

    @property
    def description(self) -> str:
        """Description of the command."""
        return "Set the maximum number of tool call loop repetitions"

    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return [
            "!/set(tool-loop-max-repeats=3)",
            "!/set(tool-loop-max-repeats=5)",
        ]

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """
        normalized = param_name.lower().replace("_", "-").replace(" ", "-")
        return normalized == self.name or normalized in [
            a.lower() for a in self.aliases
        ]

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle setting the maximum number of tool call loop repetitions.

        Args:
            param_value: The maximum number of repetitions
            current_state: The current session state
            context: Optional command context

        Returns:
            A result containing success/failure status and updated state
        """
        if param_value is None:
            return CommandHandlerResult(
                success=False, message="Max repeats value must be specified"
            )

        try:
            max_repeats = int(param_value)
            if max_repeats < 2:
                return CommandHandlerResult(
                    success=False, message="Max repeats must be at least 2"
                )
        except ValueError:
            return CommandHandlerResult(
                success=False,
                message=f"Invalid max repeats value: {param_value}. Must be an integer.",
            )

        # Create new state with updated tool loop max repeats setting
        new_state = current_state.with_loop_config(
            current_state.loop_config.with_tool_loop_max_repeats(max_repeats)
        )

        return CommandHandlerResult(
            success=True,
            message=f"Tool call loop max repeats set to {max_repeats}",
            new_state=new_state,
        )


class ToolLoopTTLHandler(BaseCommandHandler):
    """Handler for setting the tool call loop TTL."""

    def __init__(self) -> None:
        """Initialize the tool loop TTL handler."""
        super().__init__("tool-loop-ttl")

    @property
    def aliases(self) -> list[str]:
        """Aliases for the parameter name."""
        return ["tool_loop_ttl", "ttl"]

    @property
    def description(self) -> str:
        """Description of the command."""
        return "Set the tool call loop time-to-live in seconds"

    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return [
            "!/set(tool-loop-ttl=60)",
            "!/set(tool-loop-ttl=120)",
        ]

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """
        normalized = param_name.lower().replace("_", "-").replace(" ", "-")
        return normalized == self.name or normalized in [
            a.lower() for a in self.aliases
        ]

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle setting the tool call loop TTL.

        Args:
            param_value: The TTL in seconds
            current_state: The current session state
            context: Optional command context

        Returns:
            A result containing success/failure status and updated state
        """
        if param_value is None:
            return CommandHandlerResult(
                success=False, message="TTL value must be specified"
            )

        try:
            ttl = int(param_value)
            if ttl < 1:
                return CommandHandlerResult(
                    success=False, message="TTL must be at least 1 second"
                )
        except ValueError:
            return CommandHandlerResult(
                success=False,
                message=f"Invalid TTL value: {param_value}. Must be an integer.",
            )

        # Create new state with updated tool loop TTL setting
        new_state = current_state.with_loop_config(
            current_state.loop_config.with_tool_loop_ttl(ttl)
        )

        return CommandHandlerResult(
            success=True,
            message=f"Tool call loop TTL set to {ttl} seconds",
            new_state=new_state,
        )


class ToolLoopModeHandler(BaseCommandHandler):
    """Handler for setting the tool call loop mode."""

    def __init__(self) -> None:
        """Initialize the tool loop mode handler."""
        super().__init__("tool-loop-mode")

    @property
    def aliases(self) -> list[str]:
        """Aliases for the parameter name."""
        return ["tool_loop_mode", "loop_mode"]

    @property
    def description(self) -> str:
        """Description of the command."""
        return "Set the tool call loop mode (break or chance_then_break)"

    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return [
            "!/set(tool-loop-mode=break)",
            "!/set(tool-loop-mode=chance_then_break)",
        ]

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """
        normalized = param_name.lower().replace("_", "-").replace(" ", "-")
        return normalized == self.name or normalized in [
            a.lower() for a in self.aliases
        ]

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle setting the tool call loop mode.

        Args:
            param_value: The loop mode (break or chance_then_break)
            current_state: The current session state
            context: Optional command context

        Returns:
            A result containing success/failure status and updated state
        """
        if param_value is None:
            return CommandHandlerResult(
                success=False, message="Loop mode must be specified"
            )

        mode = str(param_value).lower()
        if mode not in ("break", "chance_then_break"):
            return CommandHandlerResult(
                success=False,
                message=f"Invalid loop mode: {param_value}. Use break or chance_then_break.",
            )

        # Convert string to enum
        tool_mode = (
            ToolLoopMode.BREAK if mode == "break" else ToolLoopMode.CHANCE_THEN_BREAK
        )

        # Create new state with updated tool loop mode setting
        new_state = current_state.with_loop_config(
            current_state.loop_config.with_tool_loop_mode(tool_mode)
        )

        return CommandHandlerResult(
            success=True,
            message=f"Tool call loop mode set to {mode}",
            new_state=new_state,
        )
