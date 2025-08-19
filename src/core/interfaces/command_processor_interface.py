"""
Interface for command processing.

This module defines the interface for processing commands in messages.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional

from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext


class ICommandProcessor(ABC):
    """Interface for processing commands in messages."""
    
    @abstractmethod
    async def process_commands(
        self, 
        messages: List[Any], 
        session_id: str,
        context: Optional[RequestContext] = None
    ) -> ProcessedResult:
        """Process commands in messages.
        
        Args:
            messages: The messages to process
            session_id: The session ID
            context: Optional request context
            
        Returns:
            The result of processing commands
        """
        pass
