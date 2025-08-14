"""
Response processing middleware for handling cross-cutting concerns like loop detection and API key redaction.

This module provides a pluggable middleware system that can process responses
from any backend without coupling the loop detection logic to individual connectors.

Note: For request processing (e.g., API key redaction), see request_middleware.py
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Callable
from typing import Any

from starlette.responses import StreamingResponse

from src.loop_detection import LoopDetectionConfig, LoopDetectionEvent, LoopDetector
from src.loop_detection.streaming import (
    analyze_complete_response_for_loops,
    wrap_streaming_content_with_loop_detection,
)
from src.security import APIKeyRedactor

logger = logging.getLogger(__name__)


class ResponseMiddleware:
    """
    Middleware for processing responses from any backend.

    This provides a pluggable architecture where different middleware components
    can be added without modifying individual backend connectors.
    """

    def __init__(self) -> None:
        self.middleware_stack: list[ResponseProcessor] = []

    def add_processor(self, processor: ResponseProcessor) -> None:
        """Add a response processor to the middleware stack."""
        self.middleware_stack.append(processor)

    def remove_processor(self, processor_type: type) -> None:
        """Remove all processors of a specific type."""
        self.middleware_stack = [
            p for p in self.middleware_stack if not isinstance(p, processor_type)
        ]

    async def process_response(
        self,
        response: StreamingResponse | dict[str, Any],
        request_context: RequestContext,
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
                processed_response = await processor.process(
                    processed_response, request_context
                )

        return processed_response


class ResponseProcessor:
    """Base class for response processors."""

    def should_process(
        self, response: StreamingResponse | dict[str, Any], context: RequestContext
    ) -> bool:
        """Determine if this processor should handle the response."""
        return True

    async def process(
        self, response: StreamingResponse | dict[str, Any], context: RequestContext
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
        api_key_redactor: APIKeyRedactor | None = None,
        **kwargs: Any,
    ) -> None:
        self.session_id = session_id
        self.backend_type = backend_type
        self.model = model
        self.is_streaming = is_streaming
        self.request_data = request_data
        self.api_key_redactor = api_key_redactor
        self.metadata = kwargs


class LoopDetectionProcessor(ResponseProcessor):
    """Response processor that handles loop detection for any backend."""

    def __init__(
        self,
        config: LoopDetectionConfig,
        on_loop_detected: Callable[[LoopDetectionEvent, str], None] | None = None,
    ):
        self.config = config
        self.on_loop_detected = on_loop_detected
        self._detectors: dict[str, LoopDetector] = {}  # Per-session detectors

    def should_process(
        self, response: StreamingResponse | dict[str, Any], context: RequestContext
    ) -> bool:
        """Decide if loop detection should run based on tiered settings."""
        # Session-level override via ProxyState (passed through context.metadata)
        session_override = (
            context.metadata.get("loop_detection_enabled") if context.metadata else None
        )
        if isinstance(session_override, bool):
            return session_override
        # Backend/model-level defaults via model defaults are already applied into ProxyState
        # so if not provided, fall back to global/server default
        return self.config.enabled

    def _get_or_create_detector(self, session_id: str) -> LoopDetector:
        """Get or create a loop detector for the session."""
        if session_id not in self._detectors:
            self._detectors[session_id] = LoopDetector(
                config=self.config,
                on_loop_detected=lambda event: self._handle_loop_detection(
                    event, session_id
                ),
            )
        return self._detectors[session_id]

    def _handle_loop_detection(
        self, event: LoopDetectionEvent, session_id: str
    ) -> None:
        """Handle loop detection events."""
        logger.warning(
            f"Loop detected in session {session_id}: "
            f"pattern='{event.pattern[:50]}...', "
            f"repetitions={event.repetition_count}, "
            f"confidence={event.confidence:.2f}"
        )

        if self.on_loop_detected:
            self.on_loop_detected(event, session_id)

    async def process(
        self, response: StreamingResponse | dict[str, Any], context: RequestContext
    ) -> StreamingResponse | dict[str, Any]:
        """Process response for loop detection."""
        detector = self._get_or_create_detector(context.session_id)

        if isinstance(response, StreamingResponse):
            return await self._process_streaming_response(response, detector, context)
        else:
            return await self._process_non_streaming_response(
                response, detector, context
            )

    async def _process_streaming_response(
        self,
        response: StreamingResponse,
        detector: LoopDetector,
        context: RequestContext,
    ) -> StreamingResponse:
        """Process streaming response with loop detection."""

        # Reuse the *same* StreamingResponse instance to preserve headers,
        # cookies, background tasks and, most importantly, to make sure the
        # original response object gets properly closed by Starlette/Uvicorn.

        original_content = response.body_iterator

        async def loop_detected_content() -> AsyncGenerator[Any, None]:
            # Provide a generic upstream cancel hook that will try to close the
            # original iterator if supported, without backend-specific code.
            async def cancel_upstream() -> None:
                try:
                    aclose = getattr(original_content, "aclose", None)
                    if callable(aclose):
                        await aclose()  # type: ignore[misc]
                except Exception:
                    # Ignore errors from upstream cancellation attempts
                    pass

            async for chunk in wrap_streaming_content_with_loop_detection(
                original_content.__aiter__(),
                detector,
                lambda event: self._handle_loop_detection(event, context.session_id),
                cancel_upstream,
            ):
                yield chunk

        # Patch the iterator in-place and return the original object.
        response.body_iterator = loop_detected_content()
        return response

    async def _process_non_streaming_response(
        self, response: dict[str, Any], detector: LoopDetector, context: RequestContext
    ) -> dict[str, Any]:
        """Process non-streaming response with loop detection."""

        # Handle both dict and Pydantic model responses
        response_dict = response
        if not isinstance(response, dict):
            # Convert Pydantic model to dict
            if hasattr(response, "model_dump"):
                response_dict = response.model_dump()
            elif hasattr(response, "__dict__"):
                response_dict = response.__dict__
            else:
                # If we can't convert, return as-is
                return response

        for idx, choice in enumerate(response_dict.get("choices", [])):
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

        return response_dict

    def cleanup_session(self, session_id: str) -> None:
        """Clean up detector for a session."""
        if session_id in self._detectors:
            del self._detectors[session_id]


class APIKeyRedactionProcessor(ResponseProcessor):
    """Response processor that handles API key redaction for any backend."""

    def should_process(
        self, response: StreamingResponse | dict[str, Any], context: RequestContext
    ) -> bool:
        """Only process if we have an API key redactor."""
        return context.api_key_redactor is not None

    async def process(
        self, response: StreamingResponse | dict[str, Any], context: RequestContext
    ) -> StreamingResponse | dict[str, Any]:
        """Process response for API key redaction."""
        if context.api_key_redactor is None:
            return response

        if isinstance(response, StreamingResponse):
            return await self._process_streaming_response(response, context)
        else:
            return await self._process_non_streaming_response(response, context)

    async def _process_streaming_response(
        self, response: StreamingResponse, context: RequestContext
    ) -> StreamingResponse:
        """Process streaming response with API key redaction."""
        if context.api_key_redactor is None:
            return response

        original_content = response.body_iterator

        async def redacted_content() -> AsyncGenerator[Any, None]:
            async for chunk in original_content:
                # For streaming responses, we need to parse and redact the content
                if isinstance(chunk, bytes):
                    chunk_str = chunk.decode("utf-8")
                else:
                    chunk_str = str(chunk)

                # Redact API keys in the chunk
                if context.api_key_redactor:
                    redacted_chunk = self._redact_streaming_chunk(
                        chunk_str, context.api_key_redactor
                    )
                else:
                    redacted_chunk = chunk_str

                if isinstance(chunk, bytes):
                    yield redacted_chunk.encode("utf-8")
                else:
                    yield redacted_chunk

        # Patch the iterator in-place and return the original object.
        response.body_iterator = redacted_content()
        return response

    def _redact_streaming_chunk(self, chunk: str, redactor: APIKeyRedactor) -> str:
        """Redact API keys in a streaming chunk."""
        # Handle SSE format (data: ... chunks)
        if chunk.startswith("data:"):
            # Extract the JSON part after "data: "
            if chunk.strip() == "data: [DONE]":
                return chunk

            try:
                # Remove "data: " prefix and any trailing newlines
                json_part = chunk[6:].strip()
                if json_part:
                    data = json.loads(json_part)
                    if isinstance(data, dict):
                        self._redact_openai_sse_json(data, redactor)
                    return f"data: {json.dumps(data)}\n\n"
            except (json.JSONDecodeError, Exception):
                # If we can't parse/modify, return original chunk
                pass

        # For non-SSE chunks or if parsing failed, try to redact the whole chunk
        # This is a fallback for edge cases
        return redactor.redact(chunk)

    def _redact_openai_sse_json(
        self, data: dict[str, Any], redactor: APIKeyRedactor
    ) -> None:
        """Redact content fields inside an OpenAI SSE JSON object in place."""
        for choice in data.get("choices", []):
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta", {})
            if (
                isinstance(delta, dict)
                and "content" in delta
                and isinstance(delta["content"], str)
            ):
                delta["content"] = redactor.redact(delta["content"])
            message = choice.get("message", {})
            if (
                isinstance(message, dict)
                and "content" in message
                and isinstance(message["content"], str)
            ):
                message["content"] = redactor.redact(message["content"])

    async def _process_non_streaming_response(
        self, response: dict[str, Any], context: RequestContext
    ) -> dict[str, Any]:
        """Process non-streaming response with API key redaction."""
        if context.api_key_redactor is None:
            return response

        # Handle both dict and Pydantic model responses
        response_dict = response
        if not isinstance(response, dict):
            # Convert Pydantic model to dict
            if hasattr(response, "model_dump"):
                response_dict = response.model_dump()
            elif hasattr(response, "__dict__"):
                response_dict = response.__dict__
            else:
                # If we can't convert, return as-is
                return response

        # Redact API keys in response content
        for choice in response_dict.get("choices", []):
            if not ("message" in choice and "content" in choice["message"]):
                continue

            content = choice["message"]["content"]
            if content and isinstance(content, str):
                choice["message"]["content"] = context.api_key_redactor.redact(content)

        return response_dict


# Global middleware instance
response_middleware = ResponseMiddleware()


def configure_api_key_redaction_middleware() -> None:
    """Configure the global API key redaction middleware."""
    # Remove any existing API key redaction processors
    response_middleware.remove_processor(APIKeyRedactionProcessor)

    # Add new API key redaction processor
    processor = APIKeyRedactionProcessor()
    response_middleware.add_processor(processor)


def configure_loop_detection_middleware(
    config: LoopDetectionConfig,
    on_loop_detected: Callable[[LoopDetectionEvent, str], None] | None = None,
) -> None:
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
