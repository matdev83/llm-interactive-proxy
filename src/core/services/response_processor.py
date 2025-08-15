from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from src.core.common.exceptions import BackendError, LoopDetectionError
from src.core.domain.chat import ChatResponse, StreamingChatResponse
from src.core.interfaces.loop_detector import ILoopDetector
from src.core.interfaces.response_processor import (
    IResponseMiddleware,
    IResponseProcessor,
    ProcessedResponse,
)

logger = logging.getLogger(__name__)


class ResponseProcessor(IResponseProcessor):
    """Processes responses from LLM backends.

    This service handles the processing of LLM responses, applying
    middleware components and other transformations.
    """

    def __init__(self, loop_detector: ILoopDetector | None = None, middleware: list[IResponseMiddleware] | None = None):
        """Initialize the response processor.
        
        Args:
            loop_detector: Optional loop detector for detecting repetitive patterns
            middleware: Optional list of middleware components to register
        """
        self._loop_detector = loop_detector
        self._middleware: list[tuple[int, IResponseMiddleware]] = []
        
        # Register any provided middleware with default priority
        if middleware:
            for mw in middleware:
                self._middleware.append((0, mw))

    async def process_response(
        self, response: Any, session_id: str
    ) -> ProcessedResponse:
        """Process a complete LLM response.

        Args:
            response: The raw LLM response
            session_id: The session ID associated with this request

        Returns:
            A processed response object

        Raises:
            BackendError: If there's an error processing the response
        """
        try:
            # Extract content from the response
            content, usage, metadata = self._extract_response_data(response)

            # Check for loops if loop detector is available
            if self._loop_detector and content:
                loop_result = await self._loop_detector.check_for_loops(content)
                if loop_result.has_loop:
                    raise LoopDetectionError(
                        message=f"Response loop detected ({loop_result.repetitions} repetitions)",
                        pattern=loop_result.pattern,
                        repetitions=loop_result.repetitions,
                        details=loop_result.details,
                    )

            # Create initial processed response
            processed = ProcessedResponse(
                content=content,
                usage=usage,
                metadata=metadata,
            )

            # Apply middleware
            context = {"session_id": session_id, "response_type": "complete"}
            for _, middleware in sorted(
                self._middleware, key=lambda m: m[0], reverse=True
            ):
                processed = await middleware.process(processed, session_id, context)

            return processed

        except LoopDetectionError:
            # Re-raise loop detection errors
            raise
        except Exception as e:
            # Convert all other exceptions to BackendError
            logger.error(f"Error processing response: {e!s}", exc_info=True)
            raise BackendError(
                message=f"Error processing response: {e!s}",
                details={"session_id": session_id},
            )

    def process_streaming_response(
        self, response_iterator: AsyncIterator[Any], session_id: str
    ) -> AsyncIterator[ProcessedResponse]:
        """Process a streaming LLM response.

        Args:
            response_iterator: An async iterator of response chunks
            session_id: The session ID associated with this request

        Returns:
            An async iterator of processed response chunks

        Raises:
            BackendError: If there's an error processing the response
        """

        # Create a wrapper async generator function
        async def _process_stream():
            accumulated_content = ""

            try:
                # Sort middleware by priority (higher numbers first)
                sorted_middleware = sorted(
                    self._middleware, key=lambda m: m[0], reverse=True
                )

                async for chunk in response_iterator:
                    try:
                        # Extract content from the chunk
                        content, usage, metadata = self._extract_chunk_data(chunk)

                        # Accumulate content for loop detection
                        if content:
                            accumulated_content += content

                            # Check for loops if loop detector is available and
                            # we have enough content to check
                            if self._loop_detector and len(accumulated_content) > 100:
                                loop_result = await self._loop_detector.check_for_loops(
                                    accumulated_content
                                )
                                if loop_result.has_loop:
                                    raise LoopDetectionError(
                                        message=f"Response loop detected in stream ({loop_result.repetitions} repetitions)",
                                        pattern=loop_result.pattern,
                                        repetitions=loop_result.repetitions,
                                        details=loop_result.details,
                                    )

                        # Create processed chunk
                        processed = ProcessedResponse(
                            content=content,
                            usage=usage,
                            metadata=metadata,
                        )

                        # Apply middleware
                        context = {"session_id": session_id, "response_type": "stream"}
                        for _, middleware in sorted_middleware:
                            processed = await middleware.process(
                                processed, session_id, context
                            )

                        yield processed

                    except LoopDetectionError as e:
                        # Yield error response and stop iteration
                        yield ProcessedResponse(
                            content=f"ERROR: {e!s}",
                            metadata={"error": e.to_dict()},
                        )
                        break

                    except Exception as e:
                        # Log and continue (we don't want to break the stream for minor errors)
                        logger.error(
                            f"Error processing stream chunk: {e!s}", exc_info=True
                        )
                        yield ProcessedResponse(
                            content=f"ERROR: {e!s}",
                            metadata={"error_type": "ChunkProcessingError"},
                        )

                    # Small delay to prevent overwhelming the client
                    await asyncio.sleep(0.01)

            except Exception as e:
                # Convert stream-level exceptions to BackendError
                logger.error(f"Error in stream processing: {e!s}", exc_info=True)
                yield ProcessedResponse(
                    content=f"ERROR: Stream processing failed: {e!s}",
                    metadata={"error_type": "StreamProcessingError"},
                )

        # Return the async generator
        return _process_stream()

    async def register_middleware(
        self, middleware: IResponseMiddleware, priority: int = 0
    ) -> None:
        """Register a middleware component to process responses.

        Args:
            middleware: The middleware component to register
            priority: The priority of the middleware (higher numbers run first)
        """
        self._middleware.append((priority, middleware))
        logger.debug(
            f"Registered response middleware: {middleware.__class__.__name__}, priority: {priority}"
        )

    def _extract_response_data(
        self, response: Any
    ) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
        """Extract content, usage, and metadata from a complete response.

        Args:
            response: The response to extract data from

        Returns:
            Tuple of (content, usage, metadata)
        """
        content = ""
        usage = None
        metadata = {}

        # Handle our domain model
        if isinstance(response, ChatResponse):
            metadata["model"] = response.model
            metadata["id"] = response.id
            metadata["created"] = str(response.created)

            if response.choices:
                choice = response.choices[0]
                if isinstance(choice, dict) and "message" in choice:
                    message = choice["message"]
                    if isinstance(message, dict) and "content" in message:
                        content = message["content"] or ""

            if response.usage:
                usage = response.usage.model_dump()

        # Handle dictionary (for legacy support)
        elif isinstance(response, dict):
            metadata["model"] = response.get("model", "unknown")
            metadata["id"] = response.get("id", "")
            metadata["created"] = response.get("created", 0)

            choices = response.get("choices", [])
            if choices and isinstance(choices, list) and len(choices) > 0:
                choice = choices[0]
                if isinstance(choice, dict) and "message" in choice:
                    message = choice["message"]
                    if isinstance(message, dict) and "content" in message:
                        content = message.get("content") or ""

            usage = response.get("usage")

        # Handle string (direct content)
        elif isinstance(response, str):
            content = response

        return content, usage, metadata

    def _extract_chunk_data(
        self, chunk: Any
    ) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
        """Extract content, usage, and metadata from a streaming chunk.

        Args:
            chunk: The chunk to extract data from

        Returns:
            Tuple of (content, usage, metadata)
        """
        content = ""
        usage = None
        metadata = {}

        # Handle our domain model
        if isinstance(chunk, StreamingChatResponse):
            metadata["model"] = chunk.model
            metadata["id"] = chunk.id
            metadata["created"] = str(chunk.created)

            if chunk.choices:
                choice = chunk.choices[0]
                if isinstance(choice, dict) and "delta" in choice:
                    delta = choice["delta"]
                    if isinstance(delta, dict) and "content" in delta:
                        content = delta.get("content") or ""

        # Handle dictionary (for legacy support)
        elif isinstance(chunk, dict):
            metadata["model"] = chunk.get("model", "unknown")
            metadata["id"] = chunk.get("id", "")
            metadata["created"] = chunk.get("created", 0)

            choices = chunk.get("choices", [])
            if choices and isinstance(choices, list) and len(choices) > 0:
                choice = choices[0]
                if isinstance(choice, dict) and "delta" in choice:
                    delta = choice["delta"]
                    if isinstance(delta, dict) and "content" in delta:
                        content = delta.get("content") or ""

        # Handle bytes (from streaming response)
        elif isinstance(chunk, bytes):
            try:
                # Try to parse as JSON
                text = chunk.decode("utf-8").strip()
                if text.startswith("data: "):
                    text = text[6:]  # Remove "data: " prefix

                if text == "[DONE]":
                    return "", None, {"done": True}

                data = json.loads(text)
                return self._extract_chunk_data(data)
            except Exception:
                # If parsing fails, treat as raw content
                content = chunk.decode("utf-8", errors="replace")

        # Handle string (direct content)
        elif isinstance(chunk, str):
            # Try to parse as JSON if it looks like it
            if chunk.startswith(("data: {", "{")):
                try:
                    text = chunk
                    if text.startswith("data: "):
                        text = text[6:]  # Remove "data: " prefix

                    data = json.loads(text)
                    return self._extract_chunk_data(data)
                except json.JSONDecodeError:
                    pass

            content = chunk

        return content, usage, metadata
