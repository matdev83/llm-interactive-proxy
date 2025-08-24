from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from src.core.common.exceptions import BackendError, LoopDetectionError
from src.core.domain.chat import ChatResponse, StreamingChatResponse
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    IResponseProcessor,
    ProcessedResponse,
)

logger = logging.getLogger(__name__)


class ResponseProcessor(IResponseProcessor):
    def __init__(
        self,
        loop_detector: ILoopDetector | None = None,
        middleware: list[IResponseMiddleware] | None = None,
    ) -> None:
        self._loop_detector = loop_detector
        self._middleware: list[tuple[int, IResponseMiddleware]] = []
        self._background_tasks: list[asyncio.Task[Any]] = (
            []
        )  # To hold references to background tasks
        if middleware:
            for mw in middleware:
                self._middleware.append((0, mw))

    def add_background_task(self, task: asyncio.Task[Any]) -> None:
        """Add a background task to be managed by the processor."""
        self._background_tasks.append(task)

    async def register_middleware(
        self, middleware: IResponseMiddleware, priority: int = 0
    ) -> None:
        """Register a middleware component to process responses.

        Args:
            middleware: The middleware component to register
            priority: The priority of the middleware (higher numbers run first)
        """
        self._middleware.append((priority, middleware))

    async def process_response(
        self, response: Any, session_id: str
    ) -> ProcessedResponse:
        try:
            content, usage, metadata = self._extract_response_data(response)
            if isinstance(content, dict | list):
                try:
                    content = json.dumps(content)
                except Exception:
                    content = str(content)

            if self._loop_detector and content:
                loop_result = await self._loop_detector.check_for_loops(content)
                if loop_result.has_loop:
                    raise LoopDetectionError(
                        message=f"Response loop detected ({loop_result.repetitions} repetitions)",
                        pattern=loop_result.pattern,
                        repetitions=loop_result.repetitions,
                        details=loop_result.details,
                    )

            processed = ProcessedResponse(
                content=content, usage=usage, metadata=metadata
            )

            context = {"session_id": session_id, "response_type": "complete"}
            for _, middleware in sorted(
                self._middleware, key=lambda m: m[0], reverse=True
            ):
                processed = await middleware.process(processed, session_id, context)

            return processed

        except LoopDetectionError:
            raise
        except Exception as e:
            logger.error(f"Error processing response: {e!s}", exc_info=True)
            raise BackendError(
                message=f"Error processing response: {e!s}",
                details={"session_id": session_id},
            )

    def process_streaming_response(
        self, response_iterator: AsyncIterator[Any], session_id: str
    ) -> AsyncIterator[ProcessedResponse]:
        async def _process_stream() -> AsyncIterator[ProcessedResponse]:
            accumulated_content = ""
            try:
                sorted_middleware = sorted(
                    self._middleware, key=lambda m: m[0], reverse=True
                )
                async for chunk in response_iterator:
                    try:
                        content, usage, metadata = self._extract_chunk_data(chunk)
                        if content:
                            accumulated_content += content
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

                        processed = ProcessedResponse(
                            content=content, usage=usage, metadata=metadata
                        )
                        context = {"session_id": session_id, "response_type": "stream"}
                        for _, middleware in sorted_middleware:
                            processed = await middleware.process(
                                processed, session_id, context
                            )
                        yield processed

                    except LoopDetectionError:
                        raise
                    except Exception as e:
                        logger.error(
                            f"Error processing stream chunk: {e!s}", exc_info=True
                        )
                        yield ProcessedResponse(
                            content=f"ERROR: {e!s}",
                            metadata={"error_type": "ChunkProcessingError"},
                        )

                    await asyncio.sleep(0.01)

            except Exception as e:
                logger.error(f"Error in stream processing: {e!s}", exc_info=True)
                yield ProcessedResponse(
                    content=f"ERROR: Stream processing failed: {e!s}",
                    metadata={"error_type": "StreamProcessingError"},
                )

        return _process_stream()

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
                # Directly access message and content from ChatCompletionChoice
                if hasattr(choice, "message"):
                    if hasattr(choice.message, "content"):
                        content = choice.message.content or ""
                    # Handle tool_calls if present
                    if (
                        hasattr(choice.message, "tool_calls")
                        and choice.message.tool_calls
                    ):
                        metadata["tool_calls"] = [
                            tc.model_dump() for tc in choice.message.tool_calls
                        ]
            if response.usage:
                from src.core.interfaces.model_bases import DomainModel

                if isinstance(
                    response.usage, DomainModel
                ):  # Check if it's a Pydantic model
                    usage = response.usage.model_dump()
                elif isinstance(response.usage, dict):
                    usage = response.usage
                else:
                    try:
                        usage = dict(response.usage)
                    except Exception:
                        usage = None

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
            metadata["id"] = getattr(chunk, "id", "")
            metadata["created"] = str(getattr(chunk, "created", ""))

            # Extract content directly from StreamingChatResponse
            content = chunk.content or ""
            if chunk.tool_calls:
                # StreamingChatResponse.tool_calls is already list[dict[str, Any]]
                metadata["tool_calls"] = chunk.tool_calls

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
                text = chunk.decode("utf-8").strip()

                if "\ndata: " in text:
                    lines = text.split("\n")
                    for line in lines:
                        line = line.strip()
                        if line.startswith("data: "):
                            first_chunk_data = line[6:]
                            if first_chunk_data == "[DONE]":
                                return "", None, {"done": True}
                            try:
                                data = json.loads(first_chunk_data)
                                return self._extract_chunk_data(data)
                            except json.JSONDecodeError:
                                continue
                    return "", None, {}

                if text.startswith("data: "):
                    text = text[6:]

                if text == "[DONE]":
                    return "", None, {"done": True}

                data = json.loads(text)
                return self._extract_chunk_data(data)
            except Exception:
                return "", None, {"parse_error": True}

        elif isinstance(chunk, str):
            if chunk.startswith(("data: {", "{")):
                try:
                    text = chunk
                    if text.startswith("data: "):
                        text = text[6:]

                    data = json.loads(text)
                    return self._extract_chunk_data(data)
                except json.JSONDecodeError:
                    pass

            content = chunk

        return content, usage, metadata
