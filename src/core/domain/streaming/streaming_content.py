"""
StreamingContent domain model.

This module contains the StreamingContent dataclass and its core invariants,
including validation, metadata synchronization, and domain-level serialization.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import pydantic

from src.core.domain.usage_summary import UsageSummary

if TYPE_CHECKING:
    from src.core.domain.streaming.contracts import StreamingChunk

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
    usage: UsageSummary | None = None
    raw_data: Any | None = None

    def __post_init__(self) -> None:
        """Validate the streaming content after initialization."""
        self._validate()

        if self.is_empty is None:
            self.is_empty = self._compute_is_empty()
        else:
            self.is_empty = bool(self.is_empty)

        # Defensive invariant: is_empty must never mark non-empty content as empty.
        # Some generators/tests may construct StreamingContent with a stale/precomputed
        # is_empty value; if so, recompute to prevent dropping real content downstream.
        computed_is_empty = self._compute_is_empty()
        if self.is_empty and not computed_is_empty:
            self.is_empty = computed_is_empty

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
        if not isinstance(cast(Any, self.content), str | dict | bytes):
            raise ValueError(
                f"content must be str, dict, or bytes, got {type(self.content).__name__}"
            )

        if not isinstance(cast(Any, self.metadata), dict):
            raise ValueError(
                f"metadata must be dict, got {type(self.metadata).__name__}"
            )

        if not isinstance(cast(Any, self.is_done), bool):
            raise ValueError(f"is_done must be bool, got {type(self.is_done).__name__}")

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
        if self.metadata.get("error"):
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
        if isinstance(reasoning_content, str) and len(reasoning_content) > 0:
            return False

        reasoning = self.metadata.get("reasoning")
        return not (isinstance(reasoning, str) and len(reasoning) > 0)

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
        model_dump = getattr(working_content, "model_dump", None)
        if model_dump and callable(model_dump):
            working_content = model_dump()

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

    def to_typed_chunk(self) -> StreamingChunk:
        """Convert this StreamingContent to a typed StreamingChunk.

        Returns:
            A StreamingChunk with typed payload and metadata

        Note:
            This method provides a bridge to the typed contract representation
            while preserving all data and behavior.

        Important:
            Internal metadata fields (those starting with underscore, e.g.,
            `_virtual_tool_calls`, `_keepalive`) are NOT preserved in the
            typed contract. This is an intentional design decision to keep
            typed contracts clean and focused on public API fields. If you
            need internal metadata fields, use the original StreamingContent
            instance directly rather than converting to typed contract.
        """
        from src.core.domain.chat import StreamingToolCall, ToolCall
        from src.core.domain.streaming.contracts import (
            StreamingChunk,
            StreamingErrorInfo,
            StreamingMetadata,
            StreamingPayload,
            StreamingUsage,
        )
        from src.core.ports.streaming_contracts import StopChunkWithUsage

        # Determine payload kind and content
        payload: StreamingPayload
        if isinstance(self.content, StopChunkWithUsage):
            # StopChunkWithUsage should be converted to opaque_json
            # Convert to plain dict first to avoid triggering protection
            plain_dict = dict(self.content)
            payload = StreamingPayload(
                kind="opaque_json_dict", opaque_json_dict=plain_dict
            )
        elif isinstance(self.content, str):
            if len(self.content) == 0:
                payload = StreamingPayload(kind="empty")
            else:
                payload = StreamingPayload(kind="text", text=self.content)
        elif isinstance(self.content, dict):
            # Pass dict directly without JSON serialization
            payload = StreamingPayload(
                kind="opaque_json_dict", opaque_json_dict=self.content
            )
        else:
            # self.content must be bytes based on type hint if we reached here
            binary_b64 = base64.b64encode(self.content).decode("utf-8")
            payload = StreamingPayload(kind="binary", binary_b64=binary_b64)

        # Convert metadata
        metadata_dict = dict(self.metadata)
        tool_calls: list[ToolCall | StreamingToolCall] | None = None
        if "tool_calls" in metadata_dict:
            tool_calls_raw = metadata_dict.pop("tool_calls")
            if isinstance(tool_calls_raw, list):
                tool_calls = []
                for tc in tool_calls_raw:
                    if isinstance(tc, ToolCall | StreamingToolCall):
                        tool_calls.append(tc)
                    elif isinstance(tc, dict):
                        # Try StreamingToolCall first as it's more suitable for streaming chunks
                        # (e.g. has optional name/id and supports index)
                        try:
                            tool_calls.append(StreamingToolCall(**tc))
                        except (pydantic.ValidationError, TypeError, ValueError) as e1:
                            try:
                                tool_calls.append(ToolCall(**tc))
                            except (
                                pydantic.ValidationError,
                                TypeError,
                                ValueError,
                            ) as e2:
                                # If both fail, skip this tool call
                                logger.warning(
                                    f"Failed to convert tool call dict to StreamingToolCall (Error: {e1}) "
                                    f"or ToolCall (Error: {e2}): {tc}",
                                    exc_info=True,
                                )

        error: StreamingErrorInfo | None = None
        if "error" in metadata_dict:
            error_dict = metadata_dict.pop("error")
            if isinstance(error_dict, dict):
                raw_message = (
                    error_dict.get("message")
                    or error_dict.get("error")
                    or error_dict.get("details")
                )
                message = (
                    str(raw_message)
                    if raw_message not in (None, "")
                    else (str(error_dict) if error_dict else "Unknown error")
                )
                error_type = error_dict.get("type") or "api_error"
                code_value = error_dict.get("code")
                if code_value is not None and not isinstance(code_value, str):
                    code_value = str(code_value)
                try:
                    error = StreamingErrorInfo(
                        type=error_type,
                        message=message,
                        code=code_value,
                        retryable=error_dict.get("retryable"),
                        status_code=error_dict.get("status_code"),
                    )
                except (pydantic.ValidationError, TypeError, ValueError):
                    logger.warning(
                        f"Failed to convert error dict to StreamingErrorInfo: {error_dict}",
                        exc_info=True,
                    )
                    # Preserve original error dict in metadata if conversion fails
                    metadata_dict["error"] = error_dict
            elif error_dict is not None:
                # Preserve string/opaque errors as message text for client visibility.
                error = StreamingErrorInfo(type="api_error", message=str(error_dict))

        # Convert usage (from attribute or metadata)
        usage: StreamingUsage | None = None
        usage_dict = self.usage or metadata_dict.get("usage")
        if usage_dict and isinstance(usage_dict, dict):
            try:
                usage = StreamingUsage(**usage_dict)
            except (pydantic.ValidationError, TypeError, ValueError):
                logger.warning(
                    f"Failed to convert usage dict to StreamingUsage: {usage_dict}",
                    exc_info=True,
                )
        if "usage" in metadata_dict:
            metadata_dict.pop("usage")

        metadata = StreamingMetadata(
            provider=metadata_dict.get("provider"),
            stream_id=metadata_dict.get("stream_id") or self.stream_id,
            finish_reason=metadata_dict.get("finish_reason"),
            role=metadata_dict.get("role"),
            tool_calls=tool_calls,
            reasoning_content=metadata_dict.get("reasoning_content"),
            error=error,
            usage=usage,
        )

        return StreamingChunk(
            payload=payload,
            metadata=metadata,
            is_done=self.is_done,
            is_empty=bool(self.is_empty) if self.is_empty is not None else False,
            is_cancellation=self.is_cancellation,
        )

    @classmethod
    def from_typed_chunk(cls, chunk: StreamingChunk) -> StreamingContent:
        """Create a StreamingContent instance from a typed StreamingChunk.

        Args:
            chunk: The typed StreamingChunk to convert

        Returns:
            A new StreamingContent instance

        Note:
            This method provides a bridge from the typed contract representation
            back to the legacy StreamingContent format while preserving all data.

        Important:
            Internal metadata fields (those starting with underscore) that were
            lost during conversion to typed contract will NOT be restored. This
            is expected behavior - internal fields are intentionally excluded
            from typed contracts to keep them clean. If you need internal fields,
            avoid round-trip conversion through typed contracts.
        """

        # Extract content based on payload kind
        content: str | dict | bytes
        if chunk.payload.kind == "text":
            content = chunk.payload.text or ""
        elif chunk.payload.kind == "opaque_json_dict":
            content = chunk.payload.opaque_json_dict or {}
        elif chunk.payload.kind == "opaque_json":
            if chunk.payload.opaque_json:
                try:
                    content = json.loads(chunk.payload.opaque_json)
                except json.JSONDecodeError:
                    # Fallback to string if JSON parsing fails
                    content = chunk.payload.opaque_json
            else:
                content = {}
        elif chunk.payload.kind == "binary":
            if chunk.payload.binary_b64:
                content = base64.b64decode(chunk.payload.binary_b64)
            else:
                content = b""
        else:  # empty
            content = ""

        # Convert metadata back to dict
        metadata: dict[str, Any] = {}
        if chunk.metadata.provider:
            metadata["provider"] = chunk.metadata.provider
        if chunk.metadata.stream_id:
            metadata["stream_id"] = chunk.metadata.stream_id
        if chunk.metadata.finish_reason:
            metadata["finish_reason"] = chunk.metadata.finish_reason
        if chunk.metadata.role:
            metadata["role"] = chunk.metadata.role
        if chunk.metadata.reasoning_content:
            metadata["reasoning_content"] = chunk.metadata.reasoning_content

        # Convert tool_calls back to dict list
        if chunk.metadata.tool_calls:
            metadata["tool_calls"] = [
                tc.model_dump(exclude_none=True) if hasattr(tc, "model_dump") else tc
                for tc in chunk.metadata.tool_calls
            ]

        # Convert error back to dict (exclude None values to match original)
        if chunk.metadata.error:
            metadata["error"] = chunk.metadata.error.model_dump(exclude_none=True)

        # Extract usage (from metadata or as attribute)
        usage: UsageSummary | None = None
        if chunk.metadata.usage:
            usage = UsageSummary.from_dict(
                chunk.metadata.usage.model_dump(exclude_none=True)
            )

        return cls(
            content=content,
            metadata=metadata,
            is_done=chunk.is_done,
            is_empty=chunk.is_empty,
            stream_id=chunk.metadata.stream_id,
            is_cancellation=chunk.is_cancellation,
            usage=usage,
        )

    @classmethod
    def from_raw(cls, raw_data: Any) -> StreamingContent:
        """Create a StreamingContent instance from raw backend data.

        Args:
            raw_data: Raw data from backend (dict, str, bytes, ProcessedResponse, etc.)

        Returns:
            A new StreamingContent instance

        Note:
            This method delegates to RawChunkParser to maintain separation of concerns.
            The parser handles transport-neutral formats (OpenAI-style dicts, SSE, strings, bytes).
            Provider-specific formats (Anthropic events, Gemini JSON) are treated as opaque
            dict content and should be normalized by provider-specific normalizers before
            reaching this entry point. See design Flow 0 for provider normalization boundary.
        """
        from src.core.domain.streaming.parsing.raw_chunk_parser import RawChunkParser

        parser = RawChunkParser()
        return parser.parse(raw_data)


__all__ = ["StreamingContent"]
