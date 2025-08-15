from __future__ import annotations

import json
import logging
from typing import Any

from src.commands.base import CommandContext
from src.core.commands.handlers.base_handler import (
    BaseCommandHandler,
    CommandHandlerResult,
)
from src.core.domain.configuration.session_state_builder import SessionStateBuilder
from src.core.domain.session import SessionState

logger = logging.getLogger(__name__)


class ReasoningEffortHandler(BaseCommandHandler):
    """Handler for setting the reasoning effort."""
    
    def __init__(self):
        """Initialize the reasoning effort handler."""
        super().__init__("reasoning-effort", ["reasoning_effort"])
    
    @property
    def description(self) -> str:
        """Description of the parameter."""
        return "Set reasoning effort level (low, medium, high)"
    
    @property
    def examples(self) -> list[str]:
        """Examples of using this parameter."""
        return ["!/set(reasoning-effort=high)"]
    
    def handle(
        self, 
        param_value: Any, 
        current_state: SessionState,
        context: CommandContext | None = None
    ) -> CommandHandlerResult:
        """Handle setting the reasoning effort.
        
        Args:
            param_value: The reasoning effort value to set
            current_state: The current session state
            context: Optional command context
            
        Returns:
            Result of the operation
        """
        if not isinstance(param_value, str):
            return CommandHandlerResult(
                success=False,
                message="Reasoning effort value must be a string"
            )
        
        effort_val = param_value.strip().lower()
        
        # Update the state
        builder = SessionStateBuilder(current_state)
        new_state = builder.with_reasoning_effort(effort_val).build()
        
        return CommandHandlerResult(
            success=True,
            message=f"Reasoning effort set to {effort_val}",
            new_state=new_state
        )


class ReasoningConfigHandler(BaseCommandHandler):
    """Handler for setting the reasoning configuration."""
    
    def __init__(self):
        """Initialize the reasoning configuration handler."""
        super().__init__("reasoning", ["reasoning-config", "reasoning_config"])
    
    @property
    def description(self) -> str:
        """Description of the parameter."""
        return "Set unified reasoning configuration for OpenRouter"
    
    @property
    def examples(self) -> list[str]:
        """Examples of using this parameter."""
        return ["!/set(reasoning={'effort': 'medium'})"]
    
    def handle(
        self, 
        param_value: Any, 
        current_state: SessionState,
        context: CommandContext | None = None
    ) -> CommandHandlerResult:
        """Handle setting the reasoning configuration.
        
        Args:
            param_value: The reasoning config value to set
            current_state: The current session state
            context: Optional command context
            
        Returns:
            Result of the operation
        """
        config_dict: dict[str, Any] = {}
        
        # Handle JSON string or direct dictionary input
        if isinstance(param_value, str):
            try:
                config_dict = json.loads(param_value)
            except json.JSONDecodeError:
                return CommandHandlerResult(
                    success=False,
                    message="Invalid JSON in reasoning config"
                )
        elif isinstance(param_value, dict):
            config_dict = param_value
        else:
            return CommandHandlerResult(
                success=False,
                message="Reasoning config must be a JSON object or dictionary"
            )
        
        # Update the state
        builder = SessionStateBuilder(current_state)
        new_state = builder.with_reasoning_config(
            current_state.reasoning_config.with_reasoning_config(config_dict)  # type: ignore
        ).build()
        
        return CommandHandlerResult(
            success=True,
            message=f"Reasoning config set to {config_dict}",
            new_state=new_state
        )


class ThinkingBudgetHandler(BaseCommandHandler):
    """Handler for setting the thinking budget."""
    
    def __init__(self):
        """Initialize the thinking budget handler."""
        super().__init__("thinking-budget", ["thinking_budget"])
    
    @property
    def description(self) -> str:
        """Description of the parameter."""
        return "Set Gemini thinking budget (128-32768 tokens)"
    
    @property
    def examples(self) -> list[str]:
        """Examples of using this parameter."""
        return ["!/set(thinking-budget=2048)"]
    
    def handle(
        self, 
        param_value: Any, 
        current_state: SessionState,
        context: CommandContext | None = None
    ) -> CommandHandlerResult:
        """Handle setting the thinking budget.
        
        Args:
            param_value: The thinking budget value to set
            current_state: The current session state
            context: Optional command context
            
        Returns:
            Result of the operation
        """
        # Convert to int
        try:
            if isinstance(param_value, str):
                budget_val = int(param_value.strip())
            elif isinstance(param_value, int | float):
                budget_val = int(param_value)
            else:
                return CommandHandlerResult(
                    success=False,
                    message="Thinking budget must be an integer"
                )
        except ValueError:
            return CommandHandlerResult(
                success=False,
                message="Thinking budget must be an integer"
            )
        
        # Validate range
        if budget_val < 128 or budget_val > 32768:
            return CommandHandlerResult(
                success=False,
                message="Thinking budget must be between 128 and 32768 tokens"
            )
        
        # Update the state
        builder = SessionStateBuilder(current_state)
        new_state = builder.with_thinking_budget(budget_val).build()
        
        return CommandHandlerResult(
            success=True,
            message=f"Thinking budget set to {budget_val}",
            new_state=new_state
        )


class TemperatureHandler(BaseCommandHandler):
    """Handler for setting the temperature."""
    
    def __init__(self):
        """Initialize the temperature handler."""
        super().__init__("temperature")
    
    @property
    def description(self) -> str:
        """Description of the parameter."""
        return "Set the temperature for the model (0.0-2.0)"
    
    @property
    def examples(self) -> list[str]:
        """Examples of using this parameter."""
        return ["!/set(temperature=0.7)"]
    
    def handle(
        self, 
        param_value: Any, 
        current_state: SessionState,
        context: CommandContext | None = None
    ) -> CommandHandlerResult:
        """Handle setting the temperature.
        
        Args:
            param_value: The temperature value to set
            current_state: The current session state
            context: Optional command context
            
        Returns:
            Result of the operation
        """
        # Convert to float
        try:
            if isinstance(param_value, str):
                temp_val = float(param_value.strip())
            elif isinstance(param_value, int | float):
                temp_val = float(param_value)
            else:
                return CommandHandlerResult(
                    success=False,
                    message="Temperature must be a number"
                )
        except ValueError:
            return CommandHandlerResult(
                success=False,
                message="Temperature must be a number"
            )
        
        # Validate range
        if temp_val < 0.0 or temp_val > 2.0:
            return CommandHandlerResult(
                success=False,
                message="Temperature must be between 0.0 and 2.0"
            )
        
        # Update the state
        builder = SessionStateBuilder(current_state)
        new_state = builder.with_temperature(temp_val).build()
        
        return CommandHandlerResult(
            success=True,
            message=f"Temperature set to {temp_val}",
            new_state=new_state
        )
