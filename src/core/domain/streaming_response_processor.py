"""
Streaming response processor interfaces and utilities.

This module provides interfaces and utilities for processing streaming
responses in a consistent way, regardless of the source or format.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class StreamingContent:
    """Represents a piece of content from a streaming response.

    This class normalizes streaming content from various sources into a consistent
    structure that can be processed by streaming response processors.
    """

    def __init__(
        self,
        content: str = "",
        is_done: bool = False,
        is_cancellation: bool = False,
        metadata: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        raw_data: Any | None = None,
    ) -> None:
        """Initialize a streaming content chunk.

        Args:
            content: The text content of the chunk
            is_done: Whether this is the final chunk in the stream
            is_cancellation: Whether this chunk represents a cancellation event
            metadata: Additional metadata about the chunk
            usage: Token usage information, if available
            raw_data: The original raw data from the stream
        """
        self.content = content
        self.is_done = is_done
        self.is_cancellation = is_cancellation
        self.metadata = metadata or {}
        self.usage = usage
        self.raw_data = raw_data

    @property
    def is_empty(self) -> bool:
        """Whether this chunk contains no actual content."""
        return not bool(self.content)

    def to_bytes(self) -> bytes:
        """Convert this chunk to a bytes representation for streaming."""
        if self.is_done:
            return b"data: [DONE]\n\n"

        # Simplified serialization for streaming
        data = {"choices": [{"delta": {"content": self.content}}]}

        # Add metadata if available
        for key in ["id", "model", "created"]:
            if key in self.metadata:
                data[key] = self.metadata[key]

        return f"data: {json.dumps(data)}\n\n".encode()

    @classmethod
    def from_raw(cls, data: Any) -> StreamingContent:
        """Create a StreamingContent instance from raw streaming data.

        This method handles parsing various formats of streaming data:
        - Bytes from SSE streams
        - Dictionaries with OpenAI-compatible format
        - Strings
        - Domain StreamingChatResponse objects

        Args:
            data: The raw streaming data to parse

        Returns:
            A normalized StreamingContent instance
        """
        # Handle bytes (typical from SSE streams)
        if isinstance(data, bytes):
            try:
                text = data.decode("utf-8").strip()

                # Check for "[DONE]" marker
                if text == "data: [DONE]":
                    return cls(is_done=True, raw_data=data)

                # Handle standard SSE format
                if text.startswith("data: "):
                    text = text[6:]  # Remove "data: " prefix

                    # Check again for "[DONE]" without prefix
                    if text == "[DONE]":
                        return cls(is_done=True, raw_data=data)

                    try:
                        # Try parsing as JSON
                        json_data = json.loads(text)
                        return cls.from_raw(json_data)
                    except json.JSONDecodeError:
                        # If not valid JSON, treat as plain text
                        return cls(content=text, raw_data=data)

                # If not in SSE format, try direct parsing
                try:
                    json_data = json.loads(text)
                    return cls.from_raw(json_data)
                except json.JSONDecodeError:
                    # If not valid JSON, treat as plain text
                    return cls(content=text, raw_data=data)

            except Exception as e:
                logger.warning(f"Error parsing bytes data: {e}")
                return cls(content="", metadata={"parse_error": True}, raw_data=data)

        # Handle dictionary format (typically from OpenAI-compatible APIs)
        elif isinstance(data, dict):
            content = ""
            metadata = {
                "id": data.get("id", ""),
                "model": data.get("model", "unknown"),
                "created": data.get("created", 0),
            }

            # Extract content from choices
            choices = data.get("choices", [])
            if choices and isinstance(choices, list) and len(choices) > 0:
                choice = choices[0]
                if isinstance(choice, dict):
                    # Handle delta format (streaming)
                    if "delta" in choice:
                        delta = choice["delta"]
                        if isinstance(delta, dict) and "content" in delta:
                            content = delta.get("content") or ""
                    # Handle message format (non-streaming)
                    elif "message" in choice:
                        message = choice["message"]
                        if isinstance(message, dict) and "content" in message:
                            content = message.get("content") or ""

            # Extract usage if available
            usage = data.get("usage")

            return cls(content=content, metadata=metadata, usage=usage, raw_data=data)

        # Handle string (direct content)
        elif isinstance(data, str):
            # Check if it might be JSON
            if data.strip().startswith(("{", "[")):
                try:
                    json_data = json.loads(data)
                    return cls.from_raw(json_data)
                except json.JSONDecodeError:
                    pass

            # Otherwise treat as plain text content
            return cls(content=data, raw_data=data)

        # Handle domain StreamingChatResponse objects
        elif hasattr(data, "choices") and hasattr(data, "model"):
            content = ""
            metadata = {
                "id": getattr(data, "id", ""),
                "model": getattr(data, "model", "unknown"),
                "created": getattr(data, "created", 0),
            }

            # Extract content directly if available
            if hasattr(data, "content") and data.content:
                content = data.content

            # Extract from choices as fallback
            elif data.choices and len(data.choices) > 0:
                choice = data.choices[0]
                if isinstance(choice, dict) and "delta" in choice:
                    delta = choice["delta"]
                    if isinstance(delta, dict) and "content" in delta:
                        content = delta.get("content") or ""

            # Extract usage if available
            usage = getattr(data, "usage", None)

            return cls(content=content, metadata=metadata, usage=usage, raw_data=data)

        # Handle StreamingContent objects directly
        elif isinstance(data, StreamingContent):
            return data

        # Fall back to empty content for unknown types
        else:
            logger.warning(
                f"Unhandled data type in StreamingContent.from_raw: {type(data)}"
            )
            return cls(
                content="", metadata={"unknown_type": str(type(data))}, raw_data=data
            )


from abc import ABC, abstractmethod


class IStreamProcessor(ABC):
    """Interface for processing streaming content."""

    @abstractmethod
    async def process(self, content: StreamingContent) -> StreamingContent:
        """Process a streaming content chunk.

        Args:
            content: The content to process

        Returns:
            The processed content
        """


from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.loop_detection.event import LoopDetectionEvent


class LoopDetectionProcessor(IStreamProcessor):
    """Stream processor that checks for repetitive patterns in the content.

    This implementation uses a hash-based loop detection mechanism.
    """

    def __init__(self, loop_detector: ILoopDetector) -> None:
        """Initialize the loop detection processor.

        Args:
            loop_detector: The loop detector instance to use.
        """
        self.loop_detector = loop_detector

    async def process(self, content: StreamingContent) -> StreamingContent:
        """Process a streaming content chunk and check for loops.

        Args:
            content: The content to process.

        Returns:
            The processed content, potentially with a cancellation message
            if a loop is detected.
        """
        if content.is_empty and not content.is_done:
            return content

        # Process the content for loop detection
        # Ensure content is a string for the loop detector
        content_str = content.content
        detection_event = self.loop_detector.process_chunk(content_str)

        if detection_event:
            logger.warning(
                f"Loop detected in streaming response by LoopDetectionProcessor: {detection_event.pattern[:50]}..."
            )
            return self._create_cancellation_content(detection_event)
        else:
            # No loop detected, pass through the content
            return content

    def _create_cancellation_content(
        self, detection_event: LoopDetectionEvent
    ) -> StreamingContent:
        """Create a StreamingContent object with a cancellation message."""
        payload = (
            f"[Response cancelled: Loop detected - Pattern "
            f"'{detection_event.pattern[:30]}...' repeated "
            f"{detection_event.repetition_count} times]"
        )
        # Return as a final chunk with the cancellation message
        return StreamingContent(
            content=f"data: {json.dumps({'content': payload})}\n\n",
            is_done=True,
            is_cancellation=True,
            metadata={"loop_detected": True, "pattern": detection_event.pattern},
        )
