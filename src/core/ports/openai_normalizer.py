"""
OpenAI stream normalizer.

This module provides normalization of OpenAI-specific streaming formats
to the unified StreamingContent representation.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from src.core.domain.streaming.sentinels import SentinelManager
from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.ports.streaming.normalizer_base import BaseStreamNormalizer
from src.core.services.streaming.error_mapping import handle_streaming_error

logger = logging.getLogger(__name__)


class OpenAIStreamNormalizer(BaseStreamNormalizer):
    """Normalizer for OpenAI streaming responses.

    This normalizer handles OpenAI's SSE format:
    - Parses "data: {...}\n\n" format
    - Extracts delta content and tool calls
    - Maps finish_reason to metadata
    - Handles [DONE] sentinel
    """

    def __init__(self) -> None:
        """Initialize the OpenAI normalizer."""
        super().__init__(provider="openai")

    async def normalize_stream(
        self, stream: AsyncIterator[object], provider: str
    ) -> AsyncIterator[StreamingContent]:
        """Convert OpenAI-specific stream to StreamingContent.

        Args:
            stream: Raw stream from OpenAI backend (opaque provider-specific data)
            provider: Provider name (should be "openai")

        Yields:
            Normalized StreamingContent chunks
        """
        stream_id: str | None = None

        try:
            async for raw_chunk in stream:
                # Handle different input types
                if isinstance(raw_chunk, bytes):
                    chunk_str = raw_chunk.decode("utf-8", errors="replace")
                elif isinstance(raw_chunk, str):
                    chunk_str = raw_chunk
                else:
                    # Skip non-string/bytes chunks
                    logger.warning(
                        "Skipping non-string/bytes chunk",
                        extra={
                            "provider": self.provider,
                            "type": type(raw_chunk).__name__,
                        },
                    )
                    continue

                # Parse SSE format - may contain multiple events
                for event in self._parse_sse_events(chunk_str):
                    # Check for [DONE] sentinel
                    if event.strip() == "[DONE]":
                        # Emit final done marker
                        done_chunk = SentinelManager.create_done_chunk()
                        # Preserve stream_id if we have one
                        if stream_id:
                            done_chunk.stream_id = stream_id
                            done_chunk.metadata["stream_id"] = stream_id
                        done_chunk.metadata["provider"] = self.provider
                        yield done_chunk
                        continue

                    # Parse JSON event
                    try:
                        event_data = json.loads(event)
                    except json.JSONDecodeError as e:
                        logger.warning(
                            "Failed to parse SSE event as JSON",
                            extra={
                                "provider": self.provider,
                                "error": str(e),
                                "event_preview": event[:200] if event else "",
                            },
                        )
                        continue

                    # Extract stream_id from first chunk if available
                    if stream_id is None and "id" in event_data:
                        stream_id = event_data["id"]

                    # Convert to StreamingContent
                    normalized_chunk = self._normalize_chunk(event_data, stream_id)
                    if normalized_chunk and self.validate_chunk(normalized_chunk):
                        yield normalized_chunk
                    elif normalized_chunk is not None:
                        logger.warning(
                            "Dropping invalid normalized chunk",
                            extra={"provider": self.provider, "stream_id": stream_id},
                        )

        except Exception as e:
            # Emit error chunk
            error_chunk = await handle_streaming_error(e, stream_id, self.provider)
            yield error_chunk

    def _parse_sse_events(self, sse_data: str) -> list[str]:
        """Parse SSE format data into individual events.

        SSE format is: "data: <json>\n\n" or "data: [DONE]\n\n"

        Args:
            sse_data: Raw SSE data string

        Returns:
            List of event data strings (without "data: " prefix)
        """
        events: list[str] = []

        # Split by double newline to get individual events
        raw_events = sse_data.split("\n\n")

        for raw_event in raw_events:
            if not raw_event.strip():
                continue

            # Handle both \n\n and \r\n\r\n separators
            raw_event = raw_event.replace("\r\n", "\n")

            # Extract data lines (SSE format can have multiple lines)
            lines = raw_event.split("\n")
            data_lines: list[str] = []

            for line in lines:
                line = line.strip()
                if line.startswith("data:"):
                    # Remove "data:" prefix and strip whitespace
                    data_content = line[5:].strip()
                    data_lines.append(data_content)

            # Join multi-line data
            if data_lines:
                event_data = " ".join(data_lines)
                events.append(event_data)

        return events

    def _normalize_chunk(
        self, event_data: dict[str, Any], stream_id: str | None
    ) -> StreamingContent | None:
        """Normalize a single OpenAI chunk to StreamingContent.

        Args:
            event_data: Parsed JSON event data
            stream_id: Stream identifier

        Returns:
            Normalized StreamingContent or None if chunk should be skipped
        """
        # Extract choices array
        choices = event_data.get("choices", [])
        if not choices:
            # Empty choices - skip this chunk
            return None

        # Get first choice (OpenAI typically uses index 0)
        choice = choices[0]
        delta = choice.get("delta", {}) or {}
        if not isinstance(delta, dict):
            delta = {}

        # Extract content from delta
        raw_content = delta.get("content")
        content: str | dict | bytes
        if raw_content is None:
            content = ""
        elif isinstance(raw_content, str | dict | bytes):
            content = raw_content
        else:
            content = str(raw_content)

        # Build metadata
        metadata: dict[str, Any] = {
            "provider": self.provider,
        }

        # Add stream_id if available
        if stream_id:
            metadata["stream_id"] = stream_id

        # Add model if available
        if "model" in event_data:
            metadata["model"] = event_data["model"]

        # Add id if available
        if "id" in event_data:
            metadata["id"] = event_data["id"]

        # Add created timestamp if available
        if "created" in event_data:
            metadata["created"] = event_data["created"]

        # Add role if present in delta
        if "role" in delta:
            metadata["role"] = delta["role"]

        # Add finish_reason if present
        finish_reason = choice.get("finish_reason")
        if finish_reason:
            metadata["finish_reason"] = finish_reason

        # Add tool_calls if present and is a valid list
        tool_calls_val = delta.get("tool_calls")
        if isinstance(tool_calls_val, list) and tool_calls_val:
            metadata["tool_calls"] = tool_calls_val

        # Add tool_call_id if present
        if "tool_call_id" in delta:
            metadata["tool_call_id"] = delta["tool_call_id"]

        # Extract reasoning content if present
        reasoning_content = delta.get("reasoning_content") or delta.get("reasoning")
        if reasoning_content:
            metadata["reasoning_content"] = reasoning_content

        # Add index if available
        if "index" in choice:
            metadata["index"] = choice["index"]

        # Determine if this is a done chunk
        is_done = finish_reason is not None

        # Determine if this is an empty chunk
        is_empty = not content and not delta.get("tool_calls") and not reasoning_content

        # Capture backend error payloads for error finish reasons
        if "error" in event_data:
            metadata["error"] = event_data["error"]

        # Create normalized chunk
        chunk = self.create_normalized_chunk(
            content=content,
            metadata=metadata,
            is_done=is_done,
            is_empty=is_empty,
            stream_id=stream_id,
        )

        return chunk
