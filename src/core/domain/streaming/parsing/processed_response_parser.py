"""
ProcessedResponse parser.

This parser handles ProcessedResponse objects, which wrap content with
metadata and usage information.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.domain.streaming.parsing.parser_strategy import IParserStrategy
from src.core.domain.streaming.stop_chunk_with_usage import (
    StopChunkWithUsage,
)
from src.core.domain.streaming.streaming_content import StreamingContent

logger = logging.getLogger(__name__)


class ProcessedResponseParser(IParserStrategy):
    """Parser for ProcessedResponse objects.

    ProcessedResponse wraps content with metadata and usage. This parser
    extracts the content, merges metadata, and forwards usage information.
    """

    def can_parse(self, raw_data: Any) -> bool:
        """Check if input is a ProcessedResponse instance.

        Args:
            raw_data: The raw data to check

        Returns:
            True if raw_data is a ProcessedResponse instance
        """
        try:
            from src.core.interfaces.response_processor_interface import (
                ProcessedResponse,
            )

            return isinstance(raw_data, ProcessedResponse)
        except ImportError:
            return False

    def parse(self, raw_data: Any) -> StreamingContent:
        """Parse ProcessedResponse into StreamingContent.

        Extracts content, merges metadata, and forwards usage. Recursively
        parses nested content if needed.

        Args:
            raw_data: ProcessedResponse instance

        Returns:
            StreamingContent with merged metadata and usage

        Raises:
            ValueError: If raw_data is not a ProcessedResponse instance
        """
        from src.core.interfaces.response_processor_interface import (
            ProcessedResponse,
        )

        if not isinstance(raw_data, ProcessedResponse):
            raise ValueError(
                f"Expected ProcessedResponse, got {type(raw_data).__name__}"
            )

        metadata = dict(raw_data.metadata) if raw_data.metadata else {}
        usage = raw_data.usage
        content_val = raw_data.content

        def _finalize(result: StreamingContent) -> StreamingContent:
            """Finalize the result by merging metadata and usage."""
            merged_metadata = dict(result.metadata)
            merged_metadata.update(metadata)
            result.metadata = merged_metadata
            if usage is not None:
                result.usage = usage
            # Preserve the underlying raw payload captured by the inner parser.
            # Overwriting raw_data with the ProcessedResponse wrapper breaks downstream
            # processors that rely on provider payloads (e.g., OpenAI dicts) being
            # available in raw_data for format detection.
            if result.raw_data is None:
                result.raw_data = raw_data
            # Preserve is_done if already True on result (e.g., from StopChunkWithUsage)
            # OR if outer metadata says is_done
            if result.is_done or bool(metadata.get("is_done")):
                result.is_done = True
            # Same for is_cancellation
            if result.is_cancellation or bool(metadata.get("is_cancellation")):
                result.is_cancellation = True
            return result

        # Handle nested StreamingContent
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

        # Handle nested ProcessedResponse (recursive)
        if isinstance(content_val, ProcessedResponse):
            # Recursively parse using StreamingContent.from_raw which delegates to RawChunkParser
            parsed = StreamingContent.from_raw(content_val)
            return _finalize(parsed)

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
                StreamingContent(
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

        # Pydantic / domain stream chunks (e.g. CanonicalStreamChunk from TranslationService).
        # Without this branch, str(content_val) destroys choices/tool_calls and clients see {}.
        model_dump = getattr(content_val, "model_dump", None)
        if callable(model_dump) and not isinstance(content_val, dict | str | bytes):
            try:
                dumped = model_dump(exclude_none=True)
            except (TypeError, ValueError):
                dumped = None
            if isinstance(dumped, dict):
                parsed = StreamingContent.from_raw(dumped)
                return _finalize(parsed)

        # Handle dict, str, bytes, bytearray, list - delegate to parser chain
        if isinstance(content_val, dict | str | bytes | bytearray | list):
            # Recursively parse using StreamingContent.from_raw which delegates to RawChunkParser.
            # Note: If content_val contains provider-specific formats (e.g., Anthropic event dicts,
            # Gemini JSON), from_raw will correctly treat them as opaque dict content per the
            # provider-parsing boundary enforcement. Provider-specific formats should ideally be
            # normalized by provider normalizers before being wrapped in ProcessedResponse, but
            # if they reach here, they will be preserved as opaque content (correct behavior).
            parsed = StreamingContent.from_raw(content_val)
            return _finalize(parsed)

        # Handle other types by converting to string
        content_str = ""
        if content_val is not None:
            if isinstance(content_val, bytes):
                try:
                    content_str = content_val.decode("utf-8")
                except UnicodeDecodeError:
                    logger.warning(
                        "Could not decode bytes in ProcessedResponse: %r",
                        content_val,
                        exc_info=True,
                    )
                    content_str = ""
            else:
                content_str = str(content_val)

        return _finalize(
            StreamingContent(
                content=content_str,
                metadata={},
            )
        )


__all__ = ["ProcessedResponseParser"]
