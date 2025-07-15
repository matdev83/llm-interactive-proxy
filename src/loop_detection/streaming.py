"""
Streaming response utilities for loop detection integration.

This module provides wrappers and utilities for integrating loop detection
with streaming responses from LLM backends.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Optional, Callable, Any
from starlette.responses import StreamingResponse

from .detector import LoopDetector, LoopDetectionEvent

logger = logging.getLogger(__name__)


class LoopDetectionStreamingResponse(StreamingResponse):
    """Streaming response wrapper that integrates loop detection."""
    
    def __init__(
        self,
        content: AsyncIterator[Any],
        loop_detector: Optional[LoopDetector] = None,
        on_loop_detected: Optional[Callable[[LoopDetectionEvent], None]] = None,
        **kwargs
    ):
        self.loop_detector = loop_detector
        self.on_loop_detected = on_loop_detected
        self._cancelled = False
        
        # Wrap the content iterator with loop detection
        if loop_detector and loop_detector.is_enabled():
            content = self._wrap_content_with_detection(content)
        
        super().__init__(content, **kwargs)
    
    async def _wrap_content_with_detection(self, content: AsyncIterator[Any]) -> AsyncIterator[Any]:
        """Wrap content iterator to include loop detection."""
        try:
            async for chunk in content:
                # Check if we've been cancelled
                if self._cancelled:
                    logger.info("Streaming response cancelled due to loop detection")
                    break
                
                # Process chunk for loop detection
                if isinstance(chunk, (str, bytes)):
                    chunk_text = chunk.decode('utf-8') if isinstance(chunk, bytes) else chunk
                    
                    # Check for loops
                    detection_event = self.loop_detector.process_chunk(chunk_text)
                    if detection_event:
                        logger.warning(f"Loop detected in streaming response: {detection_event.pattern[:50]}...")
                        
                        # Trigger callback
                        if self.on_loop_detected:
                            try:
                                self.on_loop_detected(detection_event)
                            except Exception as e:
                                logger.error(f"Error in loop detection callback: {e}")
                        
                        # Cancel the stream
                        self._cancelled = True
                        
                        # Yield a final message indicating cancellation
                        cancellation_message = self._create_cancellation_message(detection_event)
                        if cancellation_message:
                            yield cancellation_message
                        break
                
                # Yield the original chunk
                yield chunk
                
        except asyncio.CancelledError:
            logger.info("Streaming response cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in loop detection streaming wrapper: {e}")
            # Continue streaming on error to avoid breaking the response
            async for chunk in content:
                yield chunk
    
    def _create_cancellation_message(self, detection_event: LoopDetectionEvent) -> Optional[str]:
        """Create a cancellation message to send when a loop is detected."""
        # Emit an SSE-compatible line so that OpenAI/Gemini style clients that
        # parse incremental JSON do not choke on raw text.  The payload is a
        # simple string wrapped in an SSE "data:" envelope followed by the
        # mandatory blank line.

        payload = (
            f"[Response cancelled: Loop detected – Pattern "
            f"'{detection_event.pattern[:30]}...' repeated "
            f"{detection_event.repetition_count} times]"
        )
        return f"data: {payload}\n\n"
    
    def cancel(self):
        """Cancel the streaming response."""
        self._cancelled = True


async def wrap_streaming_content_with_loop_detection(
    content: AsyncIterator[Any],
    loop_detector: Optional[LoopDetector] = None,
    on_loop_detected: Optional[Callable[[LoopDetectionEvent], None]] = None
) -> AsyncIterator[Any]:
    """
    Wrap streaming content with loop detection.
    
    This is a standalone function that can be used to wrap any async iterator
    with loop detection capabilities.
    """
    if not loop_detector or not loop_detector.is_enabled():
        # No loop detection, pass through unchanged
        async for chunk in content:
            yield chunk
        return
    
    cancelled = False
    
    try:
        async for chunk in content:
            if cancelled:
                break
            
            # Process chunk for loop detection
            if isinstance(chunk, (str, bytes)):
                chunk_text = chunk.decode('utf-8') if isinstance(chunk, bytes) else chunk
                
                # Check for loops
                detection_event = loop_detector.process_chunk(chunk_text)
                if detection_event:
                    logger.warning(f"Loop detected: {detection_event.pattern[:50]}...")
                    
                    # Trigger callback
                    if on_loop_detected:
                        try:
                            on_loop_detected(detection_event)
                        except Exception as e:
                            logger.error(f"Error in loop detection callback: {e}")
                    
                    # Cancel the stream
                    cancelled = True
                    
                    # Yield a final cancellation message
                    cancellation_message = (
                        f"data: [Response cancelled: Loop detected – Pattern "
                        f"'{detection_event.pattern[:30]}...' repeated "
                        f"{detection_event.repetition_count} times]\n\n"
                    )
                    yield cancellation_message
                    break
            
            # Yield the original chunk
            yield chunk
            
    except asyncio.CancelledError:
        logger.info("Streaming content cancelled")
        raise
    except Exception as e:
        logger.error(f"Error in loop detection wrapper: {e}")
        # Continue streaming on error
        async for chunk in content:
            yield chunk


def analyze_complete_response_for_loops(
    response_text: str,
    loop_detector: Optional[LoopDetector] = None
) -> Optional[LoopDetectionEvent]:
    """
    Analyze a complete response for loops (for non-streaming responses).
    
    Args:
        response_text: The complete response text to analyze
        loop_detector: The loop detector instance to use
        
    Returns:
        LoopDetectionEvent if a loop is detected, None otherwise
    """
    if not loop_detector or not loop_detector.is_enabled():
        return None
    
    # Reset detector state for fresh analysis
    loop_detector.reset()
    
    # Process the entire response as a single chunk
    return loop_detector.process_chunk(response_text)