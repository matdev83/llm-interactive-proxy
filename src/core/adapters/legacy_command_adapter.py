"""
Legacy Command Adapter

Bridges the old command system with the new ICommandService interface.
"""

from __future__ import annotations

import logging
from typing import Any

from src.command_parser import CommandParser
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.command_service import ICommandService

logger = logging.getLogger(__name__)


class LegacyCommandAdapter(ICommandService):
    """Adapter that wraps legacy command processing to implement ICommandService interface."""
    
    def __init__(self, command_parser: CommandParser):
        """Initialize the adapter with a legacy command parser.
        
        Args:
            command_parser: The legacy command parser
        """
        self._command_parser = command_parser
    
    async def process_commands(
        self, 
        messages: list[dict[str, Any]], 
        session_id: str
    ) -> ProcessedResult:
        """Process commands in messages.
        
        Args:
            messages: List of message dictionaries
            session_id: The session ID
            
        Returns:
            Processed result with modified messages and command results
        """
        try:
            # Use legacy command parser to process messages
            processed_messages, command_results = await self._command_parser.process_messages(
                messages, session_id
            )
            
            # Convert legacy command results to new format
            command_executed = len(command_results) > 0
            
            # Create ProcessedResult
            return ProcessedResult(
                modified_messages=processed_messages,
                command_executed=command_executed,
                command_results=command_results,
                session_updated=command_executed,
            )
            
        except Exception as e:
            logger.exception(f"Error processing commands: {e}")
            # Return original messages if command processing fails
            return ProcessedResult(
                modified_messages=messages,
                command_executed=False,
                command_results=[],
                session_updated=False,
            )
    
    def register_command(self, command_name: str, command_handler: Any) -> None:
        """Register a command handler.
        
        Args:
            command_name: The command name
            command_handler: The command handler
        """
        # Delegate to legacy command parser
        self._command_parser.register_command(command_name, command_handler)
    
    def get_available_commands(self) -> list[str]:
        """Get list of available commands.
        
        Returns:
            List of command names
        """
        # Get commands from legacy command parser
        if hasattr(self._command_parser, 'commands'):
            return list(self._command_parser.commands.keys())
        return []


def create_legacy_command_adapter(command_parser: CommandParser) -> LegacyCommandAdapter:
    """Create a legacy command adapter.
    
    Args:
        command_parser: The legacy command parser
        
    Returns:
        A legacy command adapter
    """
    return LegacyCommandAdapter(command_parser)