"""
PWD command handler for the SOLID architecture.

This module provides a command handler for printing the current project directory.
"""

from __future__ import annotations

import logging
from typing import Any

from src.commands.base import CommandContext
from src.core.commands.handlers.base_handler import (
    BaseCommandHandler,
    CommandHandlerResult,
)
from src.core.domain.session import SessionState

logger = logging.getLogger(__name__)


class PwdCommandHandler(BaseCommandHandler):
    """Handler for printing the current project directory."""
    
    def __init__(self):
        """Initialize the pwd command handler."""
        super().__init__("pwd")
    
    @property
    def description(self) -> str:
        """Description of the command."""
        return "Print the current project directory."
    
    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return ["!/pwd"]
    
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
        """Handle printing the current project directory.
        
        Args:
            param_value: Not used
            current_state: The current session state
            context: Optional command context
            
        Returns:
            A result containing success/failure status and the project directory
        """
        if current_state.project_dir:
            return CommandHandlerResult(
                success=True,
                message=current_state.project_dir
            )
        else:
            return CommandHandlerResult(
                success=False,
                message="Project directory not set."
            )
