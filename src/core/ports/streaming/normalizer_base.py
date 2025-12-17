"""
Base normalizer implementation.

This module contains BaseStreamNormalizer with shared validation/helpers
for stream normalizers. No vendor/transport dependencies allowed.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.ports.streaming.interfaces import IProviderStreamNormalizer

logger = logging.getLogger(__name__)


class BaseStreamNormalizer(IProviderStreamNormalizer):
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

        # Normalize content to a supported type to avoid validation failures
        if content is None:
            content = ""
        elif not isinstance(content, str | dict | bytes):
            content = str(content)

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
        self, stream: AsyncIterator[object], provider: str
    ) -> AsyncIterator[StreamingContent]:
        """Convert provider-specific stream to StreamingContent.

        This is the main entry point for normalization. Subclasses should
        override this method to implement provider-specific parsing logic.

        Args:
            stream: Raw stream from backend (opaque provider-specific data)
            provider: Provider name for context

        Yields:
            Normalized StreamingContent chunks
        """
        # This is a base implementation that should be overridden
        # by subclasses. For now, we'll just pass through.
        raise NotImplementedError("Subclasses must implement normalize_stream method")


__all__ = ["BaseStreamNormalizer"]
