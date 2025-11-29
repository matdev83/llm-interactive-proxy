"""
Streaming pipeline contracts and interfaces.

This module defines the core contracts for the streaming pipeline refactor,
establishing clear boundaries between producers, normalizers, processors,
and assemblers.
"""

from __future__ import annotations

import json
import logging
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol

import httpx

from src.core.common.exceptions import (
    APIConnectionError,
    APITimeoutError,
    BackendError,
    LLMProxyError,
    ParsingError,
    RateLimitExceededError,
)

logger = logging.getLogger(__name__)


class UsageChunkLeakError(LLMProxyError):
    """Raised when code attempts to stringify a usage chunk dict directly.

    This error indicates a bug where the streaming pipeline is treating
    a usage-bearing stop chunk as plain content instead of preserving
    its OpenAI-format structure for proper SSE serialization.
    """

    def __init__(self, chunk_id: str | None = None) -> None:
        msg = (
            "Attempted to stringify a StopChunkWithUsage directly. "
            "This chunk should be serialized via to_bytes() with proper OpenAI format, "
            "not converted to a plain string. "
            f"Chunk ID: {chunk_id or 'unknown'}"
        )
        super().__init__(message=msg, code=500)


class StopChunkWithUsage(dict):
    """A dict subclass that prevents accidental stringification.

    This class wraps the final stop chunk dict (containing usage data) and
    raises an error if anyone attempts to:
    - Convert it to string via str()
    - Serialize it via json.dumps() when treated as a string
    - Interpolate it in an f-string or % formatting

    The only valid way to serialize this is through StreamingContent.to_bytes()
    which handles it as an OpenAI-format chunk.

    Usage:
        stop_chunk = StopChunkWithUsage({
            "id": "chatcmpl-xxx",
            "choices": [...],
            "usage": {...}
        })
        # This will raise UsageChunkLeakError:
        str(stop_chunk)
        f"Content: {stop_chunk}"

        # This is the correct way (handled by to_bytes()):
        json.dumps(dict(stop_chunk))  # Explicitly convert to plain dict first
        # Or use the safe_json_dumps static method:
        StopChunkWithUsage.safe_json_dumps(stop_chunk)
    """

    _stringify_allowed: bool = False

    def __str__(self) -> str:
        """Raise error on string conversion unless explicitly allowed."""
        if self._stringify_allowed:
            return super().__repr__()
        raise UsageChunkLeakError(chunk_id=self.get("id"))

    def __repr__(self) -> str:
        """Safe repr for debugging - shows it's a protected chunk."""
        return f"<StopChunkWithUsage id={self.get('id')} usage={self.get('usage')}>"

    def allow_stringify(self) -> StopChunkWithUsage:
        """Temporarily allow stringification (for legitimate serialization).

        Returns self to allow chaining like: json.dumps(chunk.allow_stringify())
        But prefer using dict(chunk) for explicit conversion.
        """
        self._stringify_allowed = True
        return self

    def to_plain_dict(self) -> dict[str, Any]:
        """Convert to a plain dict for safe serialization.

        This is the safe way to get the data when you need to serialize it.
        Returns a true plain dict (not a subclass).
        """
        # Use dict() constructor to ensure we return a plain dict, not a subclass
        return dict(self)

    @staticmethod
    def safe_json_dumps(obj: Any, **kwargs: Any) -> str:
        """Safely serialize any object to JSON, converting StopChunkWithUsage to plain dict.

        This method checks if the object is a StopChunkWithUsage and converts it
        to a plain dict before calling json.dumps(). This prevents accidental
        stringification that would trigger UsageChunkLeakError.

        Args:
            obj: The object to serialize to JSON
            **kwargs: Additional arguments to pass to json.dumps()

        Returns:
            JSON string representation of the object
        """
        if isinstance(obj, StopChunkWithUsage):
            return json.dumps(dict(obj), **kwargs)
        return json.dumps(obj, **kwargs)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StopChunkWithUsage:
        """Create a StopChunkWithUsage from a plain dict.

        This is the inverse of to_plain_dict() and enables round-trip
        serialization/deserialization.

        Args:
            data: A dictionary containing the chunk data

        Returns:
            A new StopChunkWithUsage instance

        Raises:
            ValueError: If data is not a dict
        """
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")
        instance = cls(data)
        # Log creation at DEBUG level for diagnostic tracking
        logger.debug(
            "[STREAMING] StopChunkWithUsage.from_dict: Created instance, "
            "chunk_id=%s, has_usage=%s, usage=%s",
            data.get("id", "unknown"),
            "usage" in data,
            data.get("usage"),
        )
        return instance

    @classmethod
    def wrap(cls, chunk: dict[str, Any]) -> StopChunkWithUsage:
        """Wrap a dict as a StopChunkWithUsage if it has usage data.

        Args:
            chunk: A dict that may contain usage data

        Returns:
            StopChunkWithUsage if chunk has usage, otherwise returns original dict
        """
        if isinstance(chunk, cls):
            logger.debug(
                "[STREAMING] StopChunkWithUsage.wrap: Already wrapped, " "chunk_id=%s",
                chunk.get("id", "unknown"),
            )
            return chunk
        if isinstance(chunk, dict) and chunk.get("usage") and chunk.get("choices"):
            logger.debug(
                "[STREAMING] StopChunkWithUsage.wrap: Wrapping chunk with usage, "
                "chunk_id=%s, usage=%s",
                chunk.get("id", "unknown"),
                chunk.get("usage"),
            )
            return cls(chunk)
        return chunk  # type: ignore[return-value]


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
                if self.content.strip():
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

    def to_bytes(self) -> bytes:
        """Convert this chunk to bytes for transport.

        Returns:
            Bytes representation suitable for SSE streaming

        Note:
            This method handles StopChunkWithUsage specially to ensure usage data
            is serialized at the top level of the SSE chunk, not embedded in
            delta.content. This is critical for proper billing/usage reporting.
        """
        # Log SSE serialization at DEBUG level for diagnostic tracking
        content_type = type(self.content).__name__
        has_usage = (
            isinstance(self.content, dict) and "usage" in self.content
        ) or self.usage is not None
        logger.debug(
            "[STREAMING] StreamingContent.to_bytes: Serializing chunk to SSE, "
            "content_type=%s, is_done=%s, has_usage=%s, is_stop_chunk_with_usage=%s",
            content_type,
            self.is_done,
            has_usage,
            isinstance(self.content, StopChunkWithUsage),
        )

        # CRITICAL: Handle StopChunkWithUsage at the very start to ensure
        # usage data is serialized correctly at the top level, not in delta.content.
        # This prevents the usage data leak bug where JSON chunks appear in
        # conversation history.
        if isinstance(self.content, StopChunkWithUsage):
            # Convert to plain dict to avoid triggering __str__ protection
            plain_dict = dict(self.content)
            logger.debug(
                "[STREAMING] StreamingContent.to_bytes: Emitting StopChunkWithUsage "
                "as top-level SSE with usage, chunk_id=%s, usage=%s",
                plain_dict.get("id", "unknown"),
                plain_dict.get("usage"),
            )
            # Emit as proper SSE with usage at top level, then [DONE]
            return f"data: {json.dumps(plain_dict)}\n\ndata: [DONE]\n\n".encode()

        if self.is_done:
            # Check for error metadata first
            if (
                self.metadata.get("finish_reason") == "error"
                and "error" in self.metadata
            ):
                error_data = {
                    "choices": [{"delta": {}, "finish_reason": "error"}],
                    "error": self.metadata["error"],
                }

                for key in ["id", "model", "created"]:
                    if key in self.metadata:
                        error_data[key] = self.metadata[key]

                return f"data: {json.dumps(error_data)}\n\ndata: [DONE]\n\n".encode()

            # If the content already carries an error payload, preserve it even when
            # metadata is missing the error details.
            if isinstance(self.content, dict) and self.content.get("error"):
                return f"data: {json.dumps(self.content)}\n\ndata: [DONE]\n\n".encode()

            # Check for cancellation
            if self.is_cancellation and self.content:
                data = {
                    "choices": [{"delta": {"content": str(self.content)}}],
                    "finish_reason": "cancelled",
                }
                for key in ["id", "model", "created"]:
                    if key in self.metadata:
                        data[key] = self.metadata[key]
                return f"data: {json.dumps(data)}\n\ndata: [DONE]\n\n".encode()

            if self._is_empty_completion_payload():
                return b"data: [DONE]\n\n"

            # Check if there's actual content to emit with the done marker
            # This handles cases where the final chunk has both content and is_done=True
            # BUT: if content is just "[DONE]" string, treat it as a pure done marker
            content_is_done_marker = (
                self.content == "[DONE]"
                or self.content == SentinelManager.DONE_MARKER
                or self.content == b"[DONE]"
            )

            if (
                self.content is not None
                and self.content != ""
                and not content_is_done_marker
            ):
                # If content is already an OpenAI-formatted chunk, emit it then [DONE]
                if isinstance(self.content, dict) and "choices" in self.content:
                    # Inject tool_calls from metadata into the delta if present
                    tool_calls = self.metadata.get("tool_calls")
                    if isinstance(tool_calls, list) and tool_calls:
                        # Sanitize internal markers before sending to client
                        sanitized_calls = [
                            {k: v for k, v in tc.items() if not k.startswith("_")}
                            for tc in tool_calls
                            if isinstance(tc, dict)
                        ]
                        if sanitized_calls:
                            # Ensure choices and delta exist
                            content_copy = dict(self.content)
                            choices = content_copy.get("choices", [])
                            if choices and isinstance(choices[0], dict):
                                inner_delta = choices[0].get("delta", {})
                                if isinstance(inner_delta, dict):
                                    inner_delta["tool_calls"] = sanitized_calls
                                    choices[0]["delta"] = inner_delta
                                    content_copy["choices"] = choices
                            return f"data: {json.dumps(content_copy)}\n\ndata: [DONE]\n\n".encode()
                    # Use dict() to safely convert StopChunkWithUsage to plain dict
                    return f"data: {json.dumps(dict(self.content))}\n\ndata: [DONE]\n\n".encode()
                # Otherwise, fall through to normal content handling below
            else:
                # No meaningful content or content is just "[DONE]", emit [DONE]
                return b"data: [DONE]\n\n"

        # Build delta object
        delta: dict[str, Any] = {}

        # Add role if present
        role = self.metadata.get("role")
        if isinstance(role, str) and role:
            delta["role"] = role

        # Add tool_call_id if present
        tool_call_id = self.metadata.get("tool_call_id")
        if isinstance(tool_call_id, str) and tool_call_id:
            delta["tool_call_id"] = tool_call_id

        # Add tool_calls if present (sanitize internal markers before sending)
        tool_calls = self.metadata.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            # Remove internal markers like _already_processed before sending to client
            sanitized_calls = [
                {k: v for k, v in tc.items() if not k.startswith("_")}
                for tc in tool_calls
                if isinstance(tc, dict)
            ]
            if sanitized_calls:
                delta["tool_calls"] = sanitized_calls

        # Add reasoning content if present
        reasoning_value = self.metadata.get("reasoning_content") or self.metadata.get(
            "reasoning"
        )
        if isinstance(reasoning_value, str) and reasoning_value.strip():
            delta["reasoning_content"] = reasoning_value
            delta.setdefault("reasoning", reasoning_value)

        # Add main content
        if self.content is not None:
            if isinstance(self.content, bytes):
                try:
                    delta["content"] = self.content.decode("utf-8")
                except UnicodeDecodeError:
                    # Handle invalid UTF-8 bytes by using latin-1 or repr
                    delta["content"] = self.content.decode("latin-1")
            elif isinstance(self.content, dict):
                # Check if this is already an OpenAI-formatted chunk
                # If so, use it directly instead of wrapping it again
                if "choices" in self.content or "usage" in self.content:
                    # Inject tool_calls from metadata into the delta if present
                    tool_calls_to_inject = self.metadata.get("tool_calls")
                    if isinstance(tool_calls_to_inject, list) and tool_calls_to_inject:
                        # Sanitize internal markers before sending to client
                        sanitized_calls = [
                            {k: v for k, v in tc.items() if not k.startswith("_")}
                            for tc in tool_calls_to_inject
                            if isinstance(tc, dict)
                        ]
                        if sanitized_calls:
                            content_copy = dict(self.content)
                            choices = content_copy.get("choices", [])
                            if choices and isinstance(choices[0], dict):
                                inner_delta = choices[0].get("delta", {})
                                if isinstance(inner_delta, dict):
                                    inner_delta["tool_calls"] = sanitized_calls
                                    # NOTE: Keep content alongside tool_calls for clients like Kilo-Code
                                    # that parse XML tool calls from content and ignore native tool_calls.
                                    # OpenAI-compatible clients will use native tool_calls from the delta.
                                    choices[0]["delta"] = inner_delta
                                    content_copy["choices"] = choices
                            result = f"data: {json.dumps(content_copy)}\n\n"
                        else:
                            # Use dict() to safely convert StopChunkWithUsage to plain dict
                            result = f"data: {json.dumps(dict(self.content))}\n\n"
                    else:
                        # Use dict() to safely convert StopChunkWithUsage to plain dict
                        result = f"data: {json.dumps(dict(self.content))}\n\n"
                    # Append [DONE] if this is the final chunk
                    if self.is_done:
                        result += "data: [DONE]\n\n"
                    return result.encode()
                # If we reach here with a StopChunkWithUsage, something is wrong.
                # The chunk should have been handled above (it has choices+usage).
                if isinstance(self.content, StopChunkWithUsage):
                    raise UsageChunkLeakError(chunk_id=self.content.get("id"))
                delta["content"] = json.dumps(self.content)
            elif isinstance(self.content, str):
                delta["content"] = self.content
            else:
                delta["content"] = str(self.content)
        else:
            delta["content"] = str(self.content)

        # Build response data
        response_data: dict[str, Any] = {"choices": [{"delta": delta}]}

        # Add finish_reason
        finish_reason = self.metadata.get("finish_reason")
        response_data["choices"][0]["finish_reason"] = finish_reason  # type: ignore[index]

        # Add metadata fields
        for key in ["id", "model", "created"]:
            if key in self.metadata:
                response_data[key] = self.metadata[key]

        if self.usage:
            response_data["usage"] = self.usage

        result = f"data: {json.dumps(response_data)}\n\n"
        # Append [DONE] if this is the final chunk
        if self.is_done:
            result += "data: [DONE]\n\n"
        return result.encode()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation.

        Returns:
            Dictionary representation of the streaming content
        """
        content_value: str | dict | None
        if isinstance(self.content, bytes):
            try:
                content_value = self.content.decode("utf-8")
            except UnicodeDecodeError:
                # Handle invalid UTF-8 bytes by using latin-1
                content_value = self.content.decode("latin-1")
        elif isinstance(self.content, dict):
            content_value = self.content
        else:
            content_value = str(self.content)

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

    @classmethod
    def from_raw(cls, raw_data: Any) -> StreamingContent:
        """Create a StreamingContent instance from raw backend data."""
        # Log chunk entering the pipeline at DEBUG level for diagnostic tracking
        raw_type = type(raw_data).__name__
        raw_keys = (
            list(raw_data.keys())
            if isinstance(raw_data, dict)
            else (
                list(raw_data.content.keys())
                if hasattr(raw_data, "content") and isinstance(raw_data.content, dict)
                else "N/A"
            )
        )
        is_stop_chunk = isinstance(raw_data, StopChunkWithUsage) or (
            hasattr(raw_data, "content")
            and isinstance(raw_data.content, StopChunkWithUsage)
        )
        logger.debug(
            "[STREAMING] StreamingContent.from_raw: Chunk entering pipeline, "
            "type=%s, keys=%s, is_stop_chunk_with_usage=%s",
            raw_type,
            raw_keys,
            is_stop_chunk,
        )

        content: str | dict | bytes = ""
        is_done = False
        metadata: dict[str, Any] = {}
        usage: dict[str, Any] | None = None

        # Handle StreamingContent directly - just return a copy
        if isinstance(raw_data, StreamingContent):
            return StreamingContent(
                content=raw_data.content,
                is_done=raw_data.is_done,
                is_cancellation=raw_data.is_cancellation,
                metadata=dict(raw_data.metadata),
                usage=raw_data.usage,
                raw_data=raw_data.raw_data,
            )

        from src.core.interfaces.response_processor_interface import (
            ProcessedResponse,
        )

        if isinstance(raw_data, ProcessedResponse):
            metadata = dict(raw_data.metadata) if raw_data.metadata else {}
            usage = raw_data.usage
            content_val = raw_data.content

            def _finalize(result: StreamingContent) -> StreamingContent:
                merged_metadata = dict(result.metadata)
                merged_metadata.update(metadata)
                result.metadata = merged_metadata
                if usage is not None:
                    result.usage = usage
                result.raw_data = raw_data
                if bool(metadata.get("is_done")):
                    result.is_done = True
                if bool(metadata.get("is_cancellation")):
                    result.is_cancellation = True
                return result

            if isinstance(content_val, StreamingContent):
                copied = StreamingContent(
                    content=content_val.content,
                    is_done=content_val.is_done,
                    is_cancellation=content_val.is_cancellation,
                    metadata=dict(content_val.metadata),
                    usage=content_val.usage,
                    raw_data=content_val.raw_data,
                )
                return _finalize(copied)

            if isinstance(content_val, ProcessedResponse):
                return _finalize(cls.from_raw(content_val))

            # CRITICAL: Check for StopChunkWithUsage BEFORE generic dict check.
            # StopChunkWithUsage is a dict subclass that must be preserved as-is
            # to prevent usage data from leaking into delta.content.
            if isinstance(content_val, StopChunkWithUsage):
                logger.debug(
                    "[STREAMING] StreamingContent.from_raw: Preserving StopChunkWithUsage, "
                    "chunk_id=%s, has_usage=%s",
                    content_val.get("id", "unknown"),
                    "usage" in content_val,
                )
                # Preserve the StopChunkWithUsage directly as content
                return _finalize(
                    cls(
                        content=content_val,  # Keep as StopChunkWithUsage
                        is_done=True,  # Stop chunks are always final
                        metadata={
                            "id": content_val.get("id"),
                            "model": content_val.get("model"),
                            "created": content_val.get("created"),
                            "finish_reason": "stop",
                        },
                        usage=content_val.get("usage"),
                    )
                )

            if isinstance(content_val, dict | str | bytes | bytearray | list):
                return _finalize(cls.from_raw(content_val))

            content_str = ""
            if content_val is not None:
                if isinstance(content_val, bytes):
                    try:
                        content_str = content_val.decode("utf-8")
                    except UnicodeDecodeError:
                        logger.warning(
                            "Could not decode bytes in ProcessedResponse: %r",
                            content_val,
                        )
                        content_str = ""
                else:
                    content_str = str(content_val)

            return _finalize(
                cls(
                    content=content_str,
                    metadata={},
                )
            )

        if isinstance(raw_data, dict):
            # CRITICAL: Check for StopChunkWithUsage FIRST - preserve it directly
            # to prevent usage data from being extracted and lost
            if isinstance(raw_data, StopChunkWithUsage):
                logger.debug(
                    "[STREAMING] StreamingContent.from_raw: Preserving StopChunkWithUsage (direct), "
                    "chunk_id=%s, has_usage=%s",
                    raw_data.get("id", "unknown"),
                    "usage" in raw_data,
                )
                return cls(
                    content=raw_data,  # Keep as StopChunkWithUsage
                    is_done=True,
                    metadata={
                        "id": raw_data.get("id"),
                        "model": raw_data.get("model"),
                        "created": raw_data.get("created"),
                        "finish_reason": "stop",
                    },
                    usage=raw_data.get("usage"),
                )

            if raw_data.get("type") == "content_block_delta":
                delta = raw_data.get("delta", {})
                if delta.get("type") == "text_delta":
                    content = delta.get("text", "")
            elif raw_data.get("type") == "message_delta":
                usage = raw_data.get("usage")
                is_done = True
            else:
                is_done = bool(raw_data.get("done", False))
                finish_reason = None

                candidates = raw_data.get("candidates")
                if isinstance(candidates, list) and candidates:
                    candidate = candidates[0]
                    if isinstance(candidate, dict):
                        finish_reason = candidate.get("finishReason", finish_reason)
                        content_block = candidate.get("content") or {}
                        if isinstance(content_block, dict):
                            parts = content_block.get("parts")
                            if isinstance(parts, list) and parts:
                                first_part = parts[0]
                                if isinstance(first_part, dict):
                                    text_val = first_part.get("text")
                                    if isinstance(text_val, str):
                                        content = text_val
                                    function_call = first_part.get("functionCall")
                                    if isinstance(function_call, dict):
                                        metadata["tool_calls"] = [
                                            {
                                                "id": function_call.get("id")
                                                or f"call_{uuid.uuid4().hex[:8]}",
                                                "type": "function",
                                                "function": function_call,
                                            }
                                        ]
                                        finish_reason = finish_reason or "tool_calls"
                                elif isinstance(first_part, str):
                                    content = first_part
                            role = content_block.get("role")
                            if role:
                                metadata["role"] = role
                else:
                    choices = raw_data.get("choices")
                    if choices and isinstance(choices, list) and len(choices) > 0:
                        choice = choices[0]
                        if isinstance(choice, dict):
                            finish_reason = choice.get("finish_reason", finish_reason)
                            if "delta" in choice:
                                delta = choice["delta"]
                                if isinstance(delta, dict):
                                    reasoning_value = delta.get(
                                        "reasoning_content"
                                    ) or delta.get("reasoning")
                                    if reasoning_value:
                                        normalized_reasoning = (
                                            reasoning_value
                                            if isinstance(reasoning_value, str)
                                            else str(reasoning_value)
                                        )
                                        metadata["reasoning_content"] = (
                                            normalized_reasoning
                                        )
                                        metadata.setdefault(
                                            "reasoning", normalized_reasoning
                                        )
                                    content_value = delta.get("content")
                                    if content_value is not None:
                                        content = content_value
                                    tool_calls_val = delta.get("tool_calls")
                                    if (
                                        isinstance(tool_calls_val, list)
                                        and tool_calls_val
                                    ):
                                        metadata["tool_calls"] = tool_calls_val
                            elif "message" in choice:
                                message = choice["message"]
                                if isinstance(message, dict) and "content" in message:
                                    content_value = message.get("content")
                                    content = (
                                        content_value
                                        if content_value is not None
                                        else ""
                                    )
                                if isinstance(message, dict):
                                    tool_calls_val = message.get("tool_calls")
                                    if (
                                        isinstance(tool_calls_val, list)
                                        and tool_calls_val
                                    ):
                                        metadata["tool_calls"] = tool_calls_val
                            elif "text" in choice:
                                content_value = choice.get("text")
                                content = (
                                    content_value if content_value is not None else ""
                                )

                if finish_reason is not None:
                    metadata["finish_reason"] = finish_reason
                    normalized_reason = (
                        str(finish_reason).strip().lower() if finish_reason else ""
                    )
                    if normalized_reason in {
                        "error",
                        "cancelled",
                        "user_cancelled",
                        "system_cancelled",
                    }:
                        is_done = True

                # Capture top-level error from OpenAI-style error responses
                # This handles streaming error responses like rate limit errors
                # that have format: {"choices": [{"delta": {}, "finish_reason": "error"}], "error": {...}}
                if "error" in raw_data:
                    metadata["error"] = raw_data["error"]
                    # Also store the full error response as content for debugging
                    if not content:
                        content = raw_data

                if "id" in raw_data:
                    metadata["id"] = raw_data["id"]
                if "model" in raw_data:
                    metadata["model"] = raw_data["model"]
                if "created" in raw_data:
                    metadata["created"] = raw_data["created"]

                usage_metadata = raw_data.get("usageMetadata")
                if isinstance(usage_metadata, dict):
                    usage = {
                        "prompt_tokens": usage_metadata.get("promptTokenCount", 0),
                        "completion_tokens": usage_metadata.get(
                            "candidatesTokenCount", 0
                        ),
                        "total_tokens": usage_metadata.get("totalTokenCount", 0),
                    }
                else:
                    usage = raw_data.get("usage")

                # For chunks with usage data, preserve the original OpenAI-format
                # structure in content so downstream can recognize it and properly
                # serialize the usage field in the SSE output.
                if (
                    usage
                    and not content
                    and isinstance(raw_data, dict)
                    and "choices" in raw_data
                ):
                    # OpenAI-format chunk with usage - preserve structure
                    content = raw_data

        elif isinstance(raw_data, str):
            if raw_data.strip().startswith(("{", "[")):
                try:
                    parsed_json = json.loads(raw_data)
                    return cls.from_raw(parsed_json)
                except json.JSONDecodeError:
                    content = raw_data
            elif raw_data.strip().startswith("data: "):
                # Handle Server-Sent Events format
                sse_part = raw_data.strip()[6:]  # Remove "data: " prefix
                if sse_part.strip() == "[DONE]":
                    return cls(is_done=True, raw_data=raw_data)
                else:
                    try:
                        parsed_json = json.loads(sse_part)
                        return cls.from_raw(parsed_json)
                    except json.JSONDecodeError:
                        content = sse_part
            else:
                content = raw_data

        elif isinstance(raw_data, bytes | bytearray):
            try:
                decoded_str = bytes(raw_data).decode("utf-8").strip()
                if decoded_str.startswith("data: "):
                    json_part = decoded_str[6:]
                    if json_part.strip() == "[DONE]":
                        return cls(is_done=True, raw_data=raw_data)
                    else:
                        try:
                            parsed_json = json.loads(json_part)
                            return cls.from_raw(parsed_json)
                        except json.JSONDecodeError:
                            content = json_part
                else:
                    return cls.from_raw(decoded_str)
            except UnicodeDecodeError:
                logger.warning(f"Could not decode bytes: {raw_data!r}")
                content = ""
        else:
            logger.warning(
                f"Unsupported raw data type for StreamingContent: {type(raw_data)}"
            )
            content = str(raw_data)

        return cls(
            content=content,
            is_done=is_done,
            metadata=metadata,
            usage=usage,
            raw_data=raw_data,
        )


class StreamProducer(Protocol):
    """Protocol that all streaming backends must implement.

    This protocol defines the contract for backend connectors that produce
    streaming responses.
    """

    async def stream_completion(self, request: Any) -> AsyncIterator[Any]:
        """Yield raw streaming chunks from the backend.

        Args:
            request: The chat completion request

        Yields:
            Raw streaming chunks from the backend
        """
        ...

    def get_provider_name(self) -> str:
        """Return the provider name for logging/metrics.

        Returns:
            Provider name (e.g., "openai", "anthropic", "gemini")
        """
        ...


class IStreamNormalizer(ABC):
    """Interface for normalizing streaming responses.

    Normalizers convert provider-specific streaming formats into the
    unified StreamingContent representation.
    """

    @abstractmethod
    def normalize_stream(
        self, stream: AsyncIterator[Any], provider: str
    ) -> AsyncIterator[StreamingContent]:
        """Convert provider-specific stream to StreamingContent.

        Args:
            stream: Raw stream from backend
            provider: Provider name for context

        Yields:
            Normalized StreamingContent chunks
        """

    @abstractmethod
    def validate_chunk(self, chunk: StreamingContent) -> bool:
        """Validate chunk structure and metadata.

        Args:
            chunk: The chunk to validate

        Returns:
            True if valid, False otherwise
        """


class BaseStreamNormalizer(IStreamNormalizer):
    """Base implementation for stream normalizers.

    This class provides common functionality for normalizing streaming
    responses from different backends. Subclasses should implement
    provider-specific parsing logic.
    """

    # Metadata schema definition
    METADATA_FIELD_TYPE = type[Any] | tuple[type[Any], ...]
    METADATA_SCHEMA: ClassVar[dict[str, METADATA_FIELD_TYPE]] = {
        "stream_id": str,
        "provider": str,
        "model": (str, type(None)),
        "role": (str, type(None)),
        "finish_reason": (str, type(None)),
        "reasoning_content": (str, type(None)),
        "tool_calls": list,
        "index": (int, type(None)),
        "created": (int, type(None)),
        "id": (str, type(None)),
    }

    def __init__(self, provider: str) -> None:
        """Initialize the normalizer.

        Args:
            provider: The provider name for this normalizer
        """
        self.provider = provider

    def validate_chunk(self, chunk: StreamingContent) -> bool:
        """Validate chunk structure and metadata.

        This method validates that:
        1. The chunk has valid content type
        2. The chunk has valid metadata structure
        3. All metadata fields conform to the schema

        Args:
            chunk: The chunk to validate

        Returns:
            True if valid, False otherwise
        """
        try:
            # Validate content type
            if not isinstance(chunk.content, str | dict | bytes):
                logger.warning(
                    "Invalid content type in chunk",
                    extra={
                        "provider": self.provider,
                        "content_type": type(chunk.content).__name__,
                    },
                )
                return False

            # Validate metadata is a dictionary
            if not isinstance(chunk.metadata, dict):
                logger.warning(
                    "Invalid metadata type in chunk",
                    extra={
                        "provider": self.provider,
                        "metadata_type": type(chunk.metadata).__name__,
                    },
                )
                return False

            # Validate metadata schema
            if not self.validate_metadata_schema(chunk.metadata):
                return False

            # Validate boolean flags
            if not isinstance(chunk.is_done, bool):
                logger.warning(
                    "Invalid is_done type in chunk",
                    extra={
                        "provider": self.provider,
                        "is_done_type": type(chunk.is_done).__name__,
                    },
                )
                return False

            if not isinstance(chunk.is_empty, bool):
                logger.warning(
                    "Invalid is_empty type in chunk",
                    extra={
                        "provider": self.provider,
                        "is_empty_type": type(chunk.is_empty).__name__,
                    },
                )
                return False

            # Validate stream_id if present
            if chunk.stream_id is not None and not isinstance(chunk.stream_id, str):
                logger.warning(
                    "Invalid stream_id type in chunk",
                    extra={
                        "provider": self.provider,
                        "stream_id_type": type(chunk.stream_id).__name__,
                    },
                )
                return False

            return True

        except Exception as e:
            logger.error(
                "Unexpected error during chunk validation",
                exc_info=True,
                extra={"provider": self.provider, "error": str(e)},
            )
            return False

    def validate_metadata_schema(self, metadata: dict[str, Any]) -> bool:
        """Validate metadata fields against the schema.

        This method checks that all metadata fields have the correct types
        according to the METADATA_SCHEMA definition.

        Args:
            metadata: The metadata dictionary to validate

        Returns:
            True if valid, False otherwise
        """
        for field_name, expected_type in self.METADATA_SCHEMA.items():
            if field_name not in metadata:
                # Field is optional, skip validation
                continue

            value = metadata[field_name]

            # Handle union types (e.g., str | None)
            if isinstance(expected_type, tuple):
                if not isinstance(value, expected_type):
                    logger.warning(
                        "Invalid metadata field type",
                        extra={
                            "provider": self.provider,
                            "field": field_name,
                            "expected_type": expected_type,
                            "actual_type": type(value).__name__,
                        },
                    )
                    return False
            else:
                if not isinstance(value, expected_type):  # type: ignore[arg-type]
                    logger.warning(
                        "Invalid metadata field type",
                        extra={
                            "provider": self.provider,
                            "field": field_name,
                            "expected_type": getattr(
                                expected_type, "__name__", str(expected_type)
                            ),
                            "actual_type": type(value).__name__,
                        },
                    )
                    return False

            # Additional validation for specific fields
            if (
                field_name == "tool_calls"
                and isinstance(value, list)
                and not self._validate_tool_calls(value)
            ):
                return False

        return True

    def _validate_tool_calls(self, tool_calls: list[Any]) -> bool:
        """Validate tool_calls structure.

        Args:
            tool_calls: The tool_calls list to validate

        Returns:
            True if valid, False otherwise
        """
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                logger.warning(
                    "Invalid tool_call structure: not a dict",
                    extra={"provider": self.provider},
                )
                return False

            # Validate required fields in tool_call
            if "id" in tool_call and not isinstance(tool_call["id"], str):
                logger.warning(
                    "Invalid tool_call.id type",
                    extra={"provider": self.provider},
                )
                return False

            if "type" in tool_call and not isinstance(tool_call["type"], str):
                logger.warning(
                    "Invalid tool_call.type type",
                    extra={"provider": self.provider},
                )
                return False

            if "function" in tool_call:
                function = tool_call["function"]
                if not isinstance(function, dict):
                    logger.warning(
                        "Invalid tool_call.function type",
                        extra={"provider": self.provider},
                    )
                    return False

                if "name" in function and not isinstance(function["name"], str):
                    logger.warning(
                        "Invalid tool_call.function.name type",
                        extra={"provider": self.provider},
                    )
                    return False

        return True

    def create_normalized_chunk(
        self,
        content: str | dict | bytes = "",
        metadata: dict[str, Any] | None = None,
        is_done: bool = False,
        is_empty: bool = False,
        stream_id: str | None = None,
    ) -> StreamingContent:
        """Create a normalized StreamingContent chunk.

        This utility method creates a StreamingContent chunk with proper
        metadata enrichment and validation. The normalizer's provider and
        the provided stream_id take precedence over any values in metadata.

        Args:
            content: The content for the chunk
            metadata: Optional metadata dictionary
            is_done: Whether this is a terminal chunk
            is_empty: Whether this chunk is empty
            stream_id: Optional stream identifier

        Returns:
            A validated StreamingContent chunk
        """
        # Initialize metadata if not provided
        if metadata is None:
            metadata = {}
        else:
            # Make a copy to avoid mutating the input
            metadata = metadata.copy()

        # Always set provider from normalizer (takes precedence)
        metadata["provider"] = self.provider

        # Set stream_id in metadata if provided (takes precedence)
        if stream_id:
            metadata["stream_id"] = stream_id

        # Create the chunk
        chunk = StreamingContent(
            content=content,
            metadata=metadata,
            is_done=is_done,
            is_empty=is_empty,
            stream_id=stream_id,
        )

        return chunk

    def normalize_stream(
        self, stream: AsyncIterator[Any], provider: str
    ) -> AsyncIterator[StreamingContent]:
        """Convert provider-specific stream to StreamingContent.

        This is the main entry point for normalization. Subclasses should
        override this method to implement provider-specific parsing logic.

        Args:
            stream: Raw stream from backend
            provider: Provider name for context

        Yields:
            Normalized StreamingContent chunks
        """
        # This is a base implementation that should be overridden
        # by subclasses. For now, we'll just pass through.
        raise NotImplementedError("Subclasses must implement normalize_stream method")


class IStreamProcessor(ABC):
    """Interface for middleware that processes streaming content.

    Processors can observe or transform streaming content as it flows
    through the pipeline.
    """

    @abstractmethod
    async def process(self, content: StreamingContent) -> StreamingContent:
        """Transform or observe streaming content.

        Args:
            content: The content to process

        Returns:
            The processed content
        """

    def reset(self) -> None:
        """Reset processor state for new stream.

        This method should be called before processing a new stream to
        ensure clean state isolation.

        Default implementation does nothing. Override if your processor
        maintains state.
        """
        # Default implementation: no state to reset
        return None


class IStreamAssembler(ABC):
    """Interface for converting internal format to client format.

    Assemblers handle the final conversion from StreamingContent to
    client-facing formats like SSE or JSON-lines.
    """

    @abstractmethod
    def assemble_stream(
        self, stream: AsyncIterator[StreamingContent], format: str = "sse"
    ) -> AsyncIterator[bytes]:
        """Convert StreamingContent to client-facing format.

        Args:
            stream: Stream of StreamingContent chunks
            format: Output format ("sse", "json-lines", etc.)

        Yields:
            Formatted bytes ready for client transmission
        """


class SentinelManager:
    """Centralized management of stream completion markers.

    This utility ensures consistent handling of [DONE] markers across
    all backends and components.
    """

    DONE_MARKER = "[DONE]"

    @staticmethod
    def create_done_chunk() -> StreamingContent:
        """Create standardized [DONE] chunk.

        Returns:
            A StreamingContent chunk representing stream completion
        """
        return StreamingContent(
            content=SentinelManager.DONE_MARKER,
            metadata={"finish_reason": "stop"},
            is_done=True,
        )

    @staticmethod
    def is_done_marker(chunk: StreamingContent) -> bool:
        """Check if chunk is a [DONE] marker.

        Args:
            chunk: The chunk to check

        Returns:
            True if this is a done marker, False otherwise
        """
        return chunk.is_done or chunk.content == SentinelManager.DONE_MARKER

    @staticmethod
    def format_sse_done() -> bytes:
        """Format [DONE] as SSE.

        Returns:
            SSE-formatted done marker
        """
        return b"data: [DONE]\n\n"


class StreamingErrorMapper:
    """Centralized error mapping for streaming operations.

    This class provides a single point for mapping backend-specific exceptions
    to LLMProxyError variants, ensuring consistent error handling across all
    streaming operations.
    """

    @staticmethod
    def map_backend_error(
        error: Exception,
        provider: str,
        stream_id: str | None = None,
    ) -> LLMProxyError:
        """Map backend exception to LLMProxyError variant.

        This method converts provider-specific exceptions into standardized
        LLMProxyError types, ensuring consistent error handling and logging.

        Args:
            error: The exception to map
            provider: Provider name for context
            stream_id: Optional stream identifier for tracking

        Returns:
            Mapped LLMProxyError variant
        """
        details = {
            "provider": provider,
        }
        if stream_id:
            details["stream_id"] = stream_id

        # Map httpx timeout exceptions
        if isinstance(error, httpx.TimeoutException):
            return APITimeoutError(
                message=f"{provider} request timed out",
                details=details,
            )

        # Map httpx HTTP status errors
        if isinstance(error, httpx.HTTPStatusError):
            status_code = error.response.status_code
            details["status_code"] = str(status_code)
            details["response_text"] = error.response.text[:500]  # Limit size

            # Map 429 to rate limit error
            if status_code == 429:
                return RateLimitExceededError(
                    message=f"{provider} rate limit exceeded",
                    details=details,
                )

            # Map other HTTP errors to BackendError
            return BackendError(
                message=f"{provider} returned HTTP {status_code}",
                backend_name=provider,
                details=details,
                status_code=status_code,
            )

        # Map httpx connection errors
        if isinstance(error, httpx.ConnectError | httpx.ConnectTimeout):
            return APIConnectionError(
                message=f"Failed to connect to {provider}",
                details=details,
            )

        # Map JSON decode errors
        if isinstance(error, json.JSONDecodeError):
            details["error_position"] = f"line {error.lineno}, col {error.colno}"
            return ParsingError(
                message=f"Invalid JSON from {provider}",
                details=details,
            )

        # Map already-mapped LLMProxyErrors (pass through)
        if isinstance(error, LLMProxyError):
            # Enrich with streaming context if not already present
            if "provider" not in error.details:
                error.details["provider"] = provider
            if stream_id and "stream_id" not in error.details:
                error.details["stream_id"] = stream_id
            return error

        # Catch-all for unexpected errors
        logger.error(
            "Unexpected error during streaming",
            exc_info=True,
            extra={"provider": provider, "stream_id": stream_id},
        )
        return BackendError(
            message=f"Unexpected error from {provider}: {error!s}",
            backend_name=provider,
            details=details,
        )


async def handle_streaming_error(
    error: Exception,
    stream_id: str | None = None,
    provider: str = "unknown",
) -> StreamingContent:
    """Convert error to terminal StreamingContent chunk.

    This function creates a terminal chunk that represents an error condition,
    allowing errors to be propagated through the streaming pipeline in a
    structured way.

    Args:
        error: The exception that occurred
        stream_id: Optional stream identifier
        provider: Provider name for context

    Returns:
        Terminal StreamingContent chunk with error metadata
    """
    # Map the error to a standardized type
    mapped_error = StreamingErrorMapper.map_backend_error(error, provider, stream_id)

    # Determine if error is retryable
    retryable = isinstance(
        mapped_error, APITimeoutError | APIConnectionError | RateLimitExceededError
    )

    # Build error metadata
    error_metadata = {
        "type": type(mapped_error).__name__,
        "message": str(mapped_error),
        "code": getattr(mapped_error, "code", "unknown"),
        "retryable": retryable,
    }

    # Add status code if available
    if hasattr(mapped_error, "status_code"):
        error_metadata["status_code"] = mapped_error.status_code

    # Build metadata
    metadata: dict[str, Any] = {
        "provider": provider,
        "error": error_metadata,
        "finish_reason": "error",
    }

    # Only add stream_id if it's not None
    if stream_id is not None:
        metadata["stream_id"] = stream_id

    # Create terminal chunk
    return StreamingContent(
        content="",
        metadata=metadata,
        is_done=True,
        is_empty=False,
        stream_id=stream_id,
    )
