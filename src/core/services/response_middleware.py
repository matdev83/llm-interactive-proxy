"""
Response Middleware Components

This module contains middleware components for processing responses.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.interfaces.loop_detector import ILoopDetector
from src.core.interfaces.response_processor import (
    IResponseMiddleware,
    ProcessedResponse,
)

logger = logging.getLogger(__name__)


class LoggingMiddleware(IResponseMiddleware):
    """Middleware to log response details."""
    
    async def process(
        self, 
        response: ProcessedResponse, 
        session_id: str,
        context: dict[str, Any] | None = None
    ) -> ProcessedResponse:
        """Process a response, logging information as needed.
        
        Args:
            response: The processed response
            session_id: The ID of the session
            context: Additional context
            
        Returns:
            The processed response, unchanged
        """
        # Only log debug information if debug logging is enabled
        if logger.isEnabledFor(logging.DEBUG):
            response_type = context.get("response_type", "unknown") if context else "unknown"
            _ = response.content[:100] + "..." if response.content and len(response.content) > 100 else response.content
            usage_info = response.usage if response.usage else {}
            
            logger.debug(
                f"Response processed for session {session_id} ({response_type}): "
                f"content_len={len(response.content) if response.content else 0}, "
                f"usage={usage_info}"
            )
        
        # Pass through the response unchanged
        return response


class ContentFilterMiddleware(IResponseMiddleware):
    """Middleware to filter response content."""
    
    async def process(
        self, 
        response: ProcessedResponse, 
        session_id: str,
        context: dict[str, Any] | None = None
    ) -> ProcessedResponse:
        """Process a response, filtering content as needed.
        
        Args:
            response: The processed response
            session_id: The ID of the session
            context: Additional context
            
        Returns:
            The processed response with filtered content
        """
        content = response.content
        
        if not content:
            return response
        
        # Example filtering logic - remove preambles in some responses
        if content.startswith("I'll help you with that. "):
            content = content.replace("I'll help you with that. ", "", 1)
            
        if content.startswith("I'll help you. "):
            content = content.replace("I'll help you. ", "", 1)
        
        if content.startswith("Here's ") and " as requested:" in content:
            idx = content.find(" as requested:")
            if idx > 0:
                content = content[idx + 14:].lstrip()
        
        # For certain agent types, apply specific filtering
        # This would be expanded based on your requirements
        agent_type = context.get("agent_type") if context else None
        if agent_type in {"cline", "roocode"}:
            # Remove specific patterns for these agents
            content = content.replace("```\n\n```", "")
        
        # Return a new ProcessedResponse with the filtered content
        return ProcessedResponse(
            content=content,
            usage=response.usage,
            metadata=response.metadata
        )


class LoopDetectionMiddleware(IResponseMiddleware):
    """Middleware to detect response loops."""
    
    def __init__(self, loop_detector: ILoopDetector):
        """Initialize the middleware.
        
        Args:
            loop_detector: The loop detector service
        """
        self._loop_detector = loop_detector
        self._accumulated_content: dict[str, str] = {}
    
    async def process(
        self, 
        response: ProcessedResponse, 
        session_id: str,
        context: dict[str, Any] | None = None
    ) -> ProcessedResponse:
        """Process a response, checking for loops.
        
        Args:
            response: The processed response
            session_id: The ID of the session
            context: Additional context
            
        Returns:
            The processed response or an error response if loops detected
        """
        if not response.content:
            return response
        
        # Accumulate content for this session
        if session_id not in self._accumulated_content:
            self._accumulated_content[session_id] = ""
            
        self._accumulated_content[session_id] += response.content
        
        # Only check for loops if we have enough content
        content = self._accumulated_content[session_id]
        if len(content) > 100:
            try:
                # Check for loops
                loop_result = await self._loop_detector.check_for_loops(content)
                
                if loop_result.has_loop:
                    # We found a loop, return an error response
                    error_message = f"Loop detected: The response contains repetitive content. Detected {loop_result.repetitions} repetitions."
                    
                    logger.warning(f"Loop detected in session {session_id}: {loop_result.repetitions} repetitions")
                    
                    # Return error response
                    return ProcessedResponse(
                        content=error_message,
                        usage=response.usage,
                        metadata={
                            **response.metadata,
                            "error": "loop_detected",
                            "loop_info": {
                                "repetitions": loop_result.repetitions,
                                "pattern_length": len(loop_result.pattern) if loop_result.pattern else 0
                            }
                        }
                    )
            except Exception as e:
                # Log error but don't stop processing
                logger.error(f"Error in loop detection: {e}", exc_info=True)
        
        # If we get here, no loops were detected
        return response
    
    def reset_session(self, session_id: str) -> None:
        """Reset the accumulated content for a session.
        
        Args:
            session_id: The ID of the session to reset
        """
        if session_id in self._accumulated_content:
            del self._accumulated_content[session_id]