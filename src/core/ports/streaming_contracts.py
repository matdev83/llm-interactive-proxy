"""
Streaming pipeline contracts and interfaces.

This module defines the core contracts for the streaming pipeline refactor,
establishing clear boundaries between producers, normalizers, processors,
and assemblers.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

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


@dataclass
class StreamingContent:
    """Unified representation of a streaming chunk.

    This dataclass provides a typed, validated structure for streaming content
    that flows through the pipeline from backend to client.
    """

    content: str | dict | bytes = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    is_done: bool = False
    is_empty: bool = False
    stream_id: str | None = None
    is_cancellation: bool = False
    usage: dict[str, Any] | None = None
    raw_data: Any | None = None

    def __post_init__(self) -> None:
        """Validate the streaming content after initialization."""
        self._validate()

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

    def to_bytes(self) -> bytes:
        """Convert this chunk to bytes for transport.

        Returns:
            Bytes representation suitable for SSE streaming
        """
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

        # Add tool_calls if present
        tool_calls = self.metadata.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            delta["tool_calls"] = tool_calls

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
                if "choices" in self.content:
                    return f"data: {json.dumps(self.content)}\n\n".encode()
                delta["content"] = json.dumps(self.content)
            else:
                delta["content"] = str(self.content)

        # Build response data
        data = {"choices": [{"delta": delta}]}

        # Add finish_reason
        finish_reason = self.metadata.get("finish_reason")
        data["choices"][0]["finish_reason"] = finish_reason  # type: ignore[index]

        # Add metadata fields
        for key in ["id", "model", "created"]:
            if key in self.metadata:
                data[key] = self.metadata[key]

        return f"data: {json.dumps(data)}\n\n".encode()

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
    METADATA_SCHEMA = {
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
