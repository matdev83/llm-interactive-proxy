from __future__ import annotations

import logging
from typing import Any

from src.core.interfaces.response_processor import (
    IResponseMiddleware,
    ProcessedResponse,
)

logger = logging.getLogger(__name__)


class BaseResponseMiddleware(IResponseMiddleware):
    """Base class for response middleware components.
    
    Response middleware components can modify or enhance responses
    before they are returned to the client.
    """
    
    def __init__(self, name: str):
        """Initialize the base middleware.
        
        Args:
            name: The name of this middleware component
        """
        self.name = name
    
    async def process(
        self, response: ProcessedResponse, session_id: str, context: dict[str, Any]
    ) -> ProcessedResponse:
        """Process a response or response chunk.
        
        This method should be overridden by subclasses to implement
        specific processing logic.
        
        Args:
            response: The response or chunk to process
            session_id: The session ID associated with this request
            context: Additional context for processing
            
        Returns:
            The processed response or chunk
        """
        # Default implementation is a pass-through
        return response
        
    def __str__(self) -> str:
        """Get a string representation of this middleware."""
        return f"{self.__class__.__name__}({self.name})"


class ContentFilterMiddleware(BaseResponseMiddleware):
    """Middleware for filtering response content.
    
    This middleware can be used to implement content filters, such as
    profanity filters or other content moderation.
    """
    
    def __init__(
        self,
        name: str = "content_filter",
        replacements: dict[str, str] | None = None,
    ):
        """Initialize the content filter middleware.
        
        Args:
            name: The name of this middleware component
            replacements: Dictionary of strings to replace (pattern -> replacement)
        """
        super().__init__(name)
        self._replacements = replacements or {}
    
    async def process(
        self, response: ProcessedResponse, session_id: str, context: dict[str, Any]
    ) -> ProcessedResponse:
        """Process a response by applying content filters.
        
        Args:
            response: The response or chunk to process
            session_id: The session ID associated with this request
            context: Additional context for processing
            
        Returns:
            The processed response or chunk
        """
        if not response.content or not self._replacements:
            return response
            
        # Apply replacements
        content = response.content
        for pattern, replacement in self._replacements.items():
            content = content.replace(pattern, replacement)
            
        # Return a new response if content was modified
        if content != response.content:
            return ProcessedResponse(
                content=content,
                usage=response.usage,
                metadata={**response.metadata, "filtered": True},
            )
            
        return response


class LoggingMiddleware(BaseResponseMiddleware):
    """Middleware for logging responses.
    
    This middleware logs responses for debugging and monitoring.
    """
    
    def __init__(
        self,
        name: str = "response_logger",
        log_level: int = logging.DEBUG,
    ):
        """Initialize the logging middleware.
        
        Args:
            name: The name of this middleware component
            log_level: The log level to use for response logging
        """
        super().__init__(name)
        self._log_level = log_level
    
    async def process(
        self, response: ProcessedResponse, session_id: str, context: dict[str, Any]
    ) -> ProcessedResponse:
        """Process a response by logging it.
        
        Args:
            response: The response or chunk to process
            session_id: The session ID associated with this request
            context: Additional context for processing
            
        Returns:
            The original response
        """
        if logger.isEnabledFor(self._log_level):
            response_type = context.get("response_type", "unknown")
            content_preview = response.content[:100] + "..." if len(response.content) > 100 else response.content
            
            logger.log(
                self._log_level,
                f"Response [{response_type}] for session {session_id}: {content_preview}"
            )
            
            if response.usage and logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Usage for session {session_id}: {response.usage}")
                
        return response
