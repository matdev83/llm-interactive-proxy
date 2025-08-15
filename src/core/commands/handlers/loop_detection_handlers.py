from __future__ import annotations

import logging
from typing import Any

from src.commands.base import CommandContext
from src.core.commands.handlers.base_handler import (
    BaseCommandHandler,
    CommandHandlerResult,
)
from src.core.domain.configuration.session_state_builder import SessionStateBuilder
from src.core.domain.session import SessionState
from src.tool_call_loop.config import ToolLoopMode

logger = logging.getLogger(__name__)


def _parse_bool(value: Any) -> bool | None:
    """Parse a boolean value from various input formats.
    
    Args:
        value: The value to parse
        
    Returns:
        The parsed boolean value or None if parsing failed
    """
    if isinstance(value, bool):
        return value
    
    if not isinstance(value, str):
        return None
        
    val = value.strip().lower()
    if val in ("true", "1", "yes", "on"):
        return True
    if val in ("false", "0", "no", "off", "none"):
        return False
    return None


class LoopDetectionHandler(BaseCommandHandler):
    """Handler for setting whether loop detection is enabled."""
    
    def __init__(self):
        """Initialize the loop detection handler."""
        super().__init__("loop-detection", ["loop_detection"])
    
    @property
    def description(self) -> str:
        """Description of the parameter."""
        return "Enable or disable response loop detection"
    
    @property
    def examples(self) -> list[str]:
        """Examples of using this parameter."""
        return ["!/set(loop-detection=true)", "!/set(loop-detection=false)"]
    
    def handle(
        self, 
        param_value: Any, 
        current_state: SessionState,
        context: CommandContext | None = None
    ) -> CommandHandlerResult:
        """Handle setting the loop detection enabled flag.
        
        Args:
            param_value: The enabled value to set
            current_state: The current session state
            context: Optional command context
            
        Returns:
            Result of the operation
        """
        enabled = _parse_bool(param_value)
        if enabled is None:
            return CommandHandlerResult(
                success=False,
                message="Loop detection value must be a boolean (true/false)"
            )
        
        # Update the state
        builder = SessionStateBuilder(current_state)
        new_state = builder.with_loop_detection_enabled(enabled).build()
        
        return CommandHandlerResult(
            success=True,
            message=f"Loop detection {'enabled' if enabled else 'disabled'}",
            new_state=new_state
        )


class ToolLoopDetectionHandler(BaseCommandHandler):
    """Handler for setting whether tool loop detection is enabled."""
    
    def __init__(self):
        """Initialize the tool loop detection handler."""
        super().__init__("tool-loop-detection", ["tool_loop_detection"])
    
    @property
    def description(self) -> str:
        """Description of the parameter."""
        return "Enable or disable tool call loop detection"
    
    @property
    def examples(self) -> list[str]:
        """Examples of using this parameter."""
        return ["!/set(tool-loop-detection=true)", "!/set(tool-loop-detection=false)"]
    
    def handle(
        self, 
        param_value: Any, 
        current_state: SessionState,
        context: CommandContext | None = None
    ) -> CommandHandlerResult:
        """Handle setting the tool loop detection enabled flag.
        
        Args:
            param_value: The enabled value to set
            current_state: The current session state
            context: Optional command context
            
        Returns:
            Result of the operation
        """
        enabled = _parse_bool(param_value)
        if enabled is None:
            return CommandHandlerResult(
                success=False,
                message="Tool loop detection value must be a boolean (true/false)"
            )
        
        # Update the state
        builder = SessionStateBuilder(current_state)
        new_state = builder.with_tool_loop_detection_enabled(enabled).build()
        
        return CommandHandlerResult(
            success=True,
            message=f"Tool loop detection {'enabled' if enabled else 'disabled'}",
            new_state=new_state
        )


class ToolLoopMaxRepeatsHandler(BaseCommandHandler):
    """Handler for setting the tool loop max repeats."""
    
    def __init__(self):
        """Initialize the tool loop max repeats handler."""
        super().__init__("tool-loop-max-repeats", ["tool_loop_max_repeats"])
    
    @property
    def description(self) -> str:
        """Description of the parameter."""
        return "Set the maximum number of tool call pattern repetitions before detection"
    
    @property
    def examples(self) -> list[str]:
        """Examples of using this parameter."""
        return ["!/set(tool-loop-max-repeats=3)"]
    
    def handle(
        self, 
        param_value: Any, 
        current_state: SessionState,
        context: CommandContext | None = None
    ) -> CommandHandlerResult:
        """Handle setting the tool loop max repeats.
        
        Args:
            param_value: The max repeats value to set
            current_state: The current session state
            context: Optional command context
            
        Returns:
            Result of the operation
        """
        # Convert to int
        try:
            if isinstance(param_value, str):
                repeats_val = int(param_value.strip())
            elif isinstance(param_value, int | float):
                repeats_val = int(param_value)
            else:
                return CommandHandlerResult(
                    success=False,
                    message="Tool loop max repeats must be an integer"
                )
        except ValueError:
            return CommandHandlerResult(
                success=False,
                message="Tool loop max repeats must be an integer"
            )
        
        # Validate range
        if repeats_val < 2:
            return CommandHandlerResult(
                success=False,
                message="Tool loop max repeats must be at least 2"
            )
        
        # Update the state
        builder = SessionStateBuilder(current_state)
        new_state = builder.with_loop_config(
            current_state.loop_config.with_tool_loop_max_repeats(repeats_val)  # type: ignore
        ).build()
        
        return CommandHandlerResult(
            success=True,
            message=f"Tool loop max repeats set to {repeats_val}",
            new_state=new_state
        )


class ToolLoopTtlHandler(BaseCommandHandler):
    """Handler for setting the tool loop TTL."""
    
    def __init__(self):
        """Initialize the tool loop TTL handler."""
        super().__init__("tool-loop-ttl", ["tool_loop_ttl", "tool-loop-ttl-seconds", "tool_loop_ttl_seconds"])
    
    @property
    def description(self) -> str:
        """Description of the parameter."""
        return "Set the time-to-live in seconds for tool call pattern matching"
    
    @property
    def examples(self) -> list[str]:
        """Examples of using this parameter."""
        return ["!/set(tool-loop-ttl=120)"]
    
    def handle(
        self, 
        param_value: Any, 
        current_state: SessionState,
        context: CommandContext | None = None
    ) -> CommandHandlerResult:
        """Handle setting the tool loop TTL.
        
        Args:
            param_value: The TTL value to set
            current_state: The current session state
            context: Optional command context
            
        Returns:
            Result of the operation
        """
        # Convert to int
        try:
            if isinstance(param_value, str):
                ttl_val = int(param_value.strip())
            elif isinstance(param_value, int | float):
                ttl_val = int(param_value)
            else:
                return CommandHandlerResult(
                    success=False,
                    message="Tool loop TTL must be an integer"
                )
        except ValueError:
            return CommandHandlerResult(
                success=False,
                message="Tool loop TTL must be an integer"
            )
        
        # Validate range
        if ttl_val < 1:
            return CommandHandlerResult(
                success=False,
                message="Tool loop TTL must be at least 1 second"
            )
        
        # Update the state
        builder = SessionStateBuilder(current_state)
        new_state = builder.with_loop_config(
            current_state.loop_config.with_tool_loop_ttl_seconds(ttl_val)  # type: ignore
        ).build()
        
        return CommandHandlerResult(
            success=True,
            message=f"Tool loop TTL set to {ttl_val} seconds",
            new_state=new_state
        )


class ToolLoopModeHandler(BaseCommandHandler):
    """Handler for setting the tool loop mode."""
    
    def __init__(self):
        """Initialize the tool loop mode handler."""
        super().__init__("tool-loop-mode", ["tool_loop_mode"])
    
    @property
    def description(self) -> str:
        """Description of the parameter."""
        return "Set the tool loop detection mode (break, warn)"
    
    @property
    def examples(self) -> list[str]:
        """Examples of using this parameter."""
        return ["!/set(tool-loop-mode=break)", "!/set(tool-loop-mode=warn)"]
    
    def handle(
        self, 
        param_value: Any, 
        current_state: SessionState,
        context: CommandContext | None = None
    ) -> CommandHandlerResult:
        """Handle setting the tool loop mode.
        
        Args:
            param_value: The mode value to set
            current_state: The current session state
            context: Optional command context
            
        Returns:
            Result of the operation
        """
        if not isinstance(param_value, str):
            return CommandHandlerResult(
                success=False,
                message="Tool loop mode must be a string"
            )
        
        mode_val = param_value.strip().lower()
        
        # Validate mode
        try:
            mode = ToolLoopMode(mode_val)
        except ValueError:
            valid_modes = ", ".join(m.value for m in ToolLoopMode)
            return CommandHandlerResult(
                success=False,
                message=f"Invalid tool loop mode: {mode_val}. Valid modes: {valid_modes}"
            )
        
        # Update the state
        builder = SessionStateBuilder(current_state)
        new_state = builder.with_loop_config(
            current_state.loop_config.with_tool_loop_mode(mode)  # type: ignore
        ).build()
        
        return CommandHandlerResult(
            success=True,
            message=f"Tool loop mode set to {mode.value}",
            new_state=new_state
        )
