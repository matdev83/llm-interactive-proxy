"""
Response processing middleware for handling cross-cutting concerns like loop detection.

This module provides a pluggable middleware system that can process responses
from any backend without coupling the loop detection logic to individual connectors.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from starlette.responses import StreamingResponse

from src.loop_detection import LoopDetectionConfig, LoopDetectionEvent, LoopDetector
from src.loop_detection.streaming import (
    analyze_complete_response_for_loops,
    wrap_streaming_content_with_loop_detection,
)

logger = logging.getLogger(__name__)


class ResponseMiddleware:
    """
    Middleware for processing responses from any backend.
    
    This provides a pluggable architecture where different middleware components
    can be added without modifying individual backend connectors.
    """
    
    def __init__(self):
        self.middleware_stack: list[ResponseProcessor] = []
    
    def add_processor(self, processor: ResponseProcessor) -> None:
        """Add a response processor to the middleware stack."""
        self.middleware_stack.append(processor)
    
    def remove_processor(self, processor_type: type) -> None:
        """Remove all processors of a specific type."""
        self.middleware_stack = [p for p in self.middleware_stack if not isinstance(p, processor_type)]
    
    async def process_response(
        self,
        response: StreamingResponse | dict[str, Any],
        request_context: RequestContext
    ) -> StreamingResponse | dict[str, Any]:
        """
        Process a response through all middleware processors.
        
        Args:
            response: The response from the backend (streaming or dict)
            request_context: Context information about the request
            
        Returns:
            Processed response
        """
        processed_response = response
        
        for processor in self.middleware_stack:
            if processor.should_process(processed_response, request_context):
                processed_response = await processor.process(processed_response, request_context)
        
        return processed_response


class ResponseProcessor:
    """Base class for response processors."""
    
    def should_process(
        self, 
        response: StreamingResponse | dict[str, Any], 
        context: RequestContext
    ) -> bool:
        """Determine if this processor should handle the response."""
        return True
    
    async def process(
        self,
        response: StreamingResponse | dict[str, Any],
        context: RequestContext
    ) -> StreamingResponse | dict[str, Any]:
        """Process the response."""
        return response


class RequestContext:
    """Context information for request processing."""
    
    def __init__(
        self,
        session_id: str,
        backend_type: str,
        model: str,
        is_streaming: bool,
        request_data: Any = None,
        **kwargs
    ):
        self.session_id = session_id
        self.backend_type = backend_type
        self.model = model
        self.is_streaming = is_streaming
        self.request_data = request_data
        self.metadata = kwargs


class LoopDetectionProcessor(ResponseProcessor):
    """Response processor that handles loop detection for any backend."""
    
    def __init__(
        self,
        config: LoopDetectionConfig,
        on_loop_detected: Callable[[LoopDetectionEvent, str], None] | None = None
    ):
        self.config = config
        self.on_loop_detected = on_loop_detected
        self._detectors: dict[str, LoopDetector] = {}  # Per-session detectors
    
    def should_process(
        self, 
        response: StreamingResponse | dict[str, Any], 
        context: RequestContext
    ) -> bool:
        """Only process if loop detection is enabled."""
        return self.config.enabled
    
    def _get_or_create_detector(self, session_id: str) -> LoopDetector:
        """Get or create a loop detector for the session."""
        if session_id not in self._detectors:
            self._detectors[session_id] = LoopDetector(
                config=self.config,
                on_loop_detected=lambda event: self._handle_loop_detection(event, session_id)
            )
        return self._detectors[session_id]
    
    def _handle_loop_detection(self, event: LoopDetectionEvent, session_id: str):
        """Handle loop detection events."""
        logger.warning(f"Loop detected in session {session_id}: "
                      f"pattern='{event.pattern[:50]}...', "
                      f"repetitions={event.repetition_count}, "
                      f"confidence={event.confidence:.2f}")
        
        if self.on_loop_detected:
            self.on_loop_detected(event, session_id)
    
    async def process(
        self,
        response: StreamingResponse | dict[str, Any],
        context: RequestContext
    ) -> StreamingResponse | dict[str, Any]:
        """Process response for loop detection."""
        detector = self._get_or_create_detector(context.session_id)
        
        if isinstance(response, StreamingResponse):
            return await self._process_streaming_response(response, detector, context)
        else:
            return await self._process_non_streaming_response(response, detector, context)
    
    async def _process_streaming_response(
        self,
        response: StreamingResponse,
        detector: LoopDetector,
        context: RequestContext
    ) -> StreamingResponse:
        """Process streaming response with loop detection."""
        
        # Reuse the *same* StreamingResponse instance to preserve headers,
        # cookies, background tasks and, most importantly, to make sure the
        # original response object gets properly closed by Starlette/Uvicorn.

        original_content = response.body_iterator

        async def loop_detected_content():
            async for chunk in wrap_streaming_content_with_loop_detection(
                original_content, detector, self.on_loop_detected
            ):
                yield chunk

        # Patch the iterator in-place and return the original object.
        response.body_iterator = loop_detected_content()
        return response
    
    async def _process_non_streaming_response(
        self,
        response: dict[str, Any],
        detector: LoopDetector,
        context: RequestContext
    ) -> dict[str, Any]:
        """Process non-streaming response with loop detection."""
        
        modified = False
        for idx, choice in enumerate(response.get("choices", [])):
            if not ("message" in choice and "content" in choice["message"]):
                continue

            content = choice["message"]["content"] or ""
            if not content:
                continue

            detection_event = analyze_complete_response_for_loops(content, detector)
            if detection_event:
                logger.warning(
                    f"Loop detected in non-streaming response (choice {idx}): "
                    f"{detection_event.pattern[:50]}..."
                )

                choice["message"]["content"] = (
                    f"{content}\n\n[Response analysis detected potential loop: "
                    f"Pattern '{detection_event.pattern[:30]}...' repeated "
                    f"{detection_event.repetition_count} times]"
                )
                modified = True

        return response if not modified else response
    
    def cleanup_session(self, session_id: str):
        """Clean up detector for a session."""
        if session_id in self._detectors:
            del self._detectors[session_id]


# Global middleware instance
response_middleware = ResponseMiddleware()


def configure_loop_detection_middleware(
    config: LoopDetectionConfig,
    on_loop_detected: Callable[[LoopDetectionEvent, str], None] | None = None
):
    """Configure the global loop detection middleware."""
    # Remove any existing loop detection processors
    response_middleware.remove_processor(LoopDetectionProcessor)
    
    # Add new loop detection processor if enabled
    if config.enabled:
        processor = LoopDetectionProcessor(config, on_loop_detected)
        response_middleware.add_processor(processor)


def get_response_middleware() -> ResponseMiddleware:
    """Get the global response middleware instance."""
    return response_middleware