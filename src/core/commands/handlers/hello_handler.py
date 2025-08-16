"""
Hello command handler for the SOLID architecture.

This module provides a command handler for returning the interactive welcome banner.
"""

from __future__ import annotations

import logging
from typing import Any

from src.commands.base import CommandContext
from src.core.commands.handlers.base_handler import BaseCommandHandler, CommandHandlerResult
from src.core.domain.configuration.session_state_builder import SessionStateBuilder
from src.core.domain.session import SessionState

logger = logging.getLogger(__name__)


class HelloCommandHandler(BaseCommandHandler):
    """Handler for returning the interactive welcome banner."""
    
    def __init__(self):
        """Initialize the hello command handler."""
        super().__init__("hello")
    
    @property
    def description(self) -> str:
        """Description of the command."""
        return "Return the interactive welcome banner"
    
    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return ["!/hello"]
    
    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.
        
        Args:
            param_name: The parameter name to check
            
        Returns:
            True if this handler can handle the parameter
        """
        return param_name.lower() == self.name
    
    def handle(
        self, 
        param_value: Any, 
        current_state: SessionState,
        context: CommandContext | None = None
    ) -> CommandHandlerResult:
        """Handle returning the interactive welcome banner.
        
        Args:
            param_value: Not used
            current_state: The current session state
            context: Optional command context
            
        Returns:
            A result containing success/failure status
        """
        # Create new state with hello_requested flag set to True
        builder = SessionStateBuilder(current_state)
        new_state = builder.build(hello_requested=True)
        
        return CommandHandlerResult(
            success=True,
            message="hello acknowledged",
            new_state=new_state
        )
