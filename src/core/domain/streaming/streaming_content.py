"""
StreamingContent domain model.

This module contains the StreamingContent dataclass and its core invariants,
including validation, metadata synchronization, and domain-level serialization.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StreamingContent:
    """Unified representation of a streaming chunk.

    This dataclass provides a typed, validated structure for streaming content
    that flows through the pipeline from backend to client.
    """

    content: str | dict | bytes = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    is_done: bool = False
    is_empty: bool | None = None
    stream_id: str | None = None
    is_cancellation: bool = False
    usage: dict[str, Any] | None = None
    raw_data: Any | None = None

    def __post_init__(self) -> None:
        """Validate the streaming content after initialization."""
        if self.is_empty is None:
            self.is_empty = self._compute_is_empty()
        else:
            self.is_empty = bool(self.is_empty)
        self._validate()
        self._synchronize_stream_id()
        self._synchronize_completion_state()

    def _synchronize_stream_id(self) -> None:
        """Ensure stream_id is reflected in both attribute and metadata."""
        meta_stream_id = self.metadata.get("stream_id")
        if (
            self.stream_id is None
            and isinstance(meta_stream_id, str)
            and meta_stream_id
        ):
            self.stream_id = meta_stream_id
        elif self.stream_id and not self.metadata.get("stream_id"):
            self.metadata["stream_id"] = self.stream_id

    def _synchronize_completion_state(self) -> None:
        """Align completion flags based on metadata hints."""
        metadata_done = self.metadata.get("is_done")
        if isinstance(metadata_done, bool) and metadata_done:
            self.is_done = True

        finish_reason = self.metadata.get("finish_reason")
        if (
            not self.is_done
            and isinstance(finish_reason, str)
            and finish_reason.strip().lower()
            in {"error", "cancelled", "user_cancelled", "system_cancelled"}
        ):
            self.is_done = True

    def _validate(self) -> None:
        """Validate chunk structure and metadata.

        Raises:
            ValueError: If validation fails
        """
        # Validate content type
        if not isinstance(self.content, str | dict | bytes):
            raise ValueError(
                f"content must be str, dict, or bytes, got {type(self.content)}"
            )

        # Validate metadata is a dictionary
        if not isinstance(self.metadata, dict):
            raise ValueError(f"metadata must be dict, got {type(self.metadata)}")

        # Validate boolean flags
        if not isinstance(self.is_done, bool):
            raise ValueError(f"is_done must be bool, got {type(self.is_done)}")
        if not isinstance(self.is_empty, bool):
            raise ValueError(f"is_empty must be bool, got {type(self.is_empty)}")
        if not isinstance(self.is_cancellation, bool):
            raise ValueError(
                f"is_cancellation must be bool, got {type(self.is_cancellation)}"
            )

        # Validate stream_id if present
        if self.stream_id is not None and not isinstance(self.stream_id, str):
            raise ValueError(
                f"stream_id must be str or None, got {type(self.stream_id)}"
            )

        # Validate metadata schema for required fields
        if self.metadata:
            # stream_id should be in metadata if present
            if "stream_id" in self.metadata and not isinstance(
                self.metadata["stream_id"], str
            ):
                raise ValueError("metadata['stream_id'] must be str")

            # provider should be string if present
            if "provider" in self.metadata and not isinstance(
                self.metadata["provider"], str
            ):
                raise ValueError("metadata['provider'] must be str")

            # Validate tool_calls structure if present
            if "tool_calls" in self.metadata:
                tool_calls = self.metadata["tool_calls"]
                if not isinstance(tool_calls, list):
                    raise ValueError("metadata['tool_calls'] must be list")

    def _compute_is_empty(self) -> bool:
        """Compute whether the chunk is empty based on its content and metadata."""
        if isinstance(self.metadata, dict) and self.metadata.get("error"):
            return False

        if self.content:
            if isinstance(self.content, str):
                # IMPORTANT: Consider whitespace-only strings as NON-EMPTY.
                # Models often stream spaces and newlines as separate deltas,
                # and dropping them causes words to be merged (e.g., "wordword"
                # instead of "word word" or missing line breaks).
                # Only truly empty strings (len == 0) should be considered empty.
                if len(self.content) > 0:
                    return False
            else:
                return False

        if self.metadata.get("role") == "tool":
            return False

        tool_calls = self.metadata.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            return False

        reasoning_content = self.metadata.get("reasoning_content")
        if isinstance(reasoning_content, str) and reasoning_content.strip():
            return False

        reasoning = self.metadata.get("reasoning")
        return not (isinstance(reasoning, str) and reasoning.strip())

    def _is_empty_completion_payload(self) -> bool:
        """Detect terminal payloads that do not carry any assistant content."""

        if not isinstance(self.content, dict):
            return False

        # Error chunks should never be treated as empty completions
        if self.content.get("error"):
            return False

        # Usage-containing chunks should not be treated as empty - they carry
        # important billing/token count information that must be transmitted
        if self.content.get("usage") or self.usage:
            return False

        tool_calls_meta = self.metadata.get("tool_calls")
        if isinstance(tool_calls_meta, list) and tool_calls_meta:
            return False

        choices = self.content.get("choices")
        if not isinstance(choices, list) or not choices:
            return False

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return False

        def _block_is_empty(block: dict[str, Any] | None) -> bool:
            if not isinstance(block, dict):
                return True
            return not any(
                block.get(key)
                for key in ("content", "tool_calls", "reasoning_content", "reasoning")
            )

        if "delta" in first_choice:
            return _block_is_empty(first_choice.get("delta"))
        if "message" in first_choice:
            return _block_is_empty(first_choice.get("message"))
        return False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation.

        Returns:
            Dictionary representation of the streaming content
        """
        # Handle Pydantic models (like CanonicalStreamChunk) by converting to dict first
        working_content = self.content
        if hasattr(working_content, "model_dump") and callable(
            working_content.model_dump
        ):
            working_content = working_content.model_dump()

        content_value: str | dict | None
        if isinstance(working_content, bytes):
            try:
                content_value = working_content.decode("utf-8")
            except UnicodeDecodeError:
                # Handle invalid UTF-8 bytes by using latin-1
                content_value = working_content.decode("latin-1")
        elif isinstance(working_content, dict):
            content_value = working_content
        else:
            content_value = str(working_content)

        return {
            "content": content_value,
            "metadata": self.metadata,
            "is_done": self.is_done,
            "is_empty": self.is_empty,
            "stream_id": self.stream_id,
            "is_cancellation": self.is_cancellation,
            "usage": self.usage,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StreamingContent:
        """Create a StreamingContent instance from a dictionary.

        This is the inverse of to_dict() and enables round-trip serialization.

        Args:
            data: Dictionary with StreamingContent fields

        Returns:
            A new StreamingContent instance

        Raises:
            ValueError: If required fields are missing or invalid
        """
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")

        # Extract fields with defaults
        content = data.get("content", "")
        metadata = data.get("metadata", {})
        is_done = data.get("is_done", False)
        is_empty = data.get("is_empty")
        stream_id = data.get("stream_id")
        is_cancellation = data.get("is_cancellation", False)
        usage = data.get("usage")

        # Validate types
        if not isinstance(metadata, dict):
            raise ValueError(f"metadata must be dict, got {type(metadata).__name__}")

        return cls(
            content=content,
            metadata=metadata,
            is_done=is_done,
            is_empty=is_empty,
            stream_id=stream_id,
            is_cancellation=is_cancellation,
            usage=usage,
        )

    def to_bytes(self) -> bytes:
        """Convert this chunk to bytes for transport.

        Returns:
            Bytes representation suitable for SSE streaming

        Note:
            This method delegates to SSESerializer to maintain separation of concerns.
            The serializer handles SSE framing, tool-call sanitization, and usage handling.
        """
        from src.core.transport.streaming.sse_serializer import SSESerializer

        serializer = SSESerializer()
        return serializer.serialize(self)

    @classmethod
    def from_raw(cls, raw_data: Any) -> StreamingContent:
        """Create a StreamingContent instance from raw backend data.

        Args:
            raw_data: Raw data from backend (dict, str, bytes, ProcessedResponse, etc.)

        Returns:
            A new StreamingContent instance

        Note:
            This method delegates to RawChunkParser to maintain separation of concerns.
            The parser handles provider-specific format parsing and normalization.
        """
        from src.core.domain.streaming.parsing.raw_chunk_parser import RawChunkParser

        parser = RawChunkParser()
        return parser.parse(raw_data)


__all__ = ["StreamingContent"]
