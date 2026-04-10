"""
Anthropic stream normalizer.

This module provides normalization of Anthropic-specific streaming formats
to the unified StreamingContent representation.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from src.core.domain.chat import StreamingFunctionCall, StreamingToolCall
from src.core.domain.streaming.sentinels import SentinelManager
from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.ports.streaming.normalizer_base import BaseStreamNormalizer
from src.core.services.streaming.error_mapping import handle_streaming_error

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SSEEvent:
    """A single Server-Sent Event (SSE) parsed from Anthropic stream.

    Provides a strongly-typed alternative to tuple[str, dict[str, Any]] for
    SSE event data.

    Attributes:
        event_type: The event type name (e.g., "message_start", "content_block_delta",
                    "content_block_stop", "error", "ping", "message_stop").
        event_data: The event data as a parsed JSON object.
    """

    event_type: str
    event_data: dict[str, Any]


class AnthropicStreamNormalizer(BaseStreamNormalizer):
    """Normalizer for Anthropic streaming responses.

    This normalizer handles Anthropic's event-based SSE format:
    - Parses event-based SSE format (message_start, content_block_delta, etc.)
    - Extracts thinking content as reasoning_content
    - Maps stop_reason to finish_reason
    - Handles message_stop event
    """

    def __init__(self) -> None:
        """Initialize the Anthropic normalizer."""
        super().__init__(provider="anthropic")

    async def normalize_stream(
        self, stream: AsyncIterator[object], provider: str
    ) -> AsyncIterator[StreamingContent]:
        """Convert Anthropic-specific stream to StreamingContent.

        Args:
            stream: Raw stream from Anthropic backend (opaque provider-specific data)
            provider: Provider name (should be "anthropic")

        Yields:
            Normalized StreamingContent chunks
        """
        stream_id: str | None = None
        message_id: str | None = None
        model: str | None = None
        role: str | None = None
        emitted_any = False
        tool_blocks: dict[int, dict[str, Any]] = {}

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

                # Parse SSE events
                for event in self._parse_sse_events(chunk_str):
                    event_type = event.event_type
                    event_data = event.event_data
                    # Handle different event types
                    if event_type == "message_start":
                        tool_blocks.clear()
                        # Extract message metadata
                        message = event_data.get("message", {})
                        message_id = message.get("id")
                        model = message.get("model")
                        role = message.get("role")

                        # Use message_id as stream_id
                        if message_id:
                            stream_id = message_id

                        # Emit initial chunk with role
                        if role:
                            chunk = self.create_normalized_chunk(
                                content="",
                                metadata={
                                    "role": role,
                                    "model": model,
                                    "id": message_id,
                                },
                                is_empty=True,
                                stream_id=stream_id,
                            )
                            if self.validate_chunk(chunk):
                                emitted_any = True
                                yield chunk
                            else:
                                logger.warning(
                                    "Dropping invalid role chunk",
                                    extra={
                                        "provider": self.provider,
                                        "stream_id": stream_id,
                                    },
                                )

                    elif event_type == "content_block_start":
                        idx = event_data.get("index", 0)
                        if not isinstance(idx, int):
                            try:
                                idx = int(idx)
                            except (TypeError, ValueError):
                                idx = 0
                        block = event_data.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            raw_name = block.get("name")
                            tool_blocks[idx] = {
                                "id": block.get("id"),
                                "name": raw_name if isinstance(raw_name, str) else "",
                                "arguments": "",
                            }
                            fn_name = tool_blocks[idx]["name"] or None
                            starter = StreamingToolCall(
                                index=idx,
                                id=tool_blocks[idx].get("id"),
                                type="function",
                                function=StreamingFunctionCall(
                                    name=fn_name,
                                    arguments="",
                                ),
                            )
                            st_dict = starter.model_dump(exclude_none=True)
                            start_chunk = self.create_normalized_chunk(
                                content="",
                                metadata={
                                    "model": model,
                                    "id": message_id,
                                    "index": idx,
                                    "tool_calls": [st_dict],
                                },
                                is_empty=False,
                                stream_id=stream_id,
                            )
                            if self.validate_chunk(start_chunk):
                                emitted_any = True
                                yield start_chunk
                            else:
                                logger.warning(
                                    "Dropping invalid tool_start chunk",
                                    extra={
                                        "provider": self.provider,
                                        "stream_id": stream_id,
                                    },
                                )
                        continue

                    elif event_type == "content_block_delta":
                        # Extract delta content
                        delta = event_data.get("delta", {})
                        delta_type = delta.get("type")

                        raw_ix = event_data.get("index", 0)
                        try:
                            index = int(raw_ix)
                        except (TypeError, ValueError):
                            index = 0

                        if delta_type == "text_delta":
                            # Regular text content
                            text = delta.get("text", "")

                            chunk = self.create_normalized_chunk(
                                content=text,
                                metadata={
                                    "model": model,
                                    "id": message_id,
                                    "index": index,
                                },
                                stream_id=stream_id,
                            )
                            if self.validate_chunk(chunk):
                                emitted_any = True
                                yield chunk
                            else:
                                logger.warning(
                                    "Dropping invalid text delta chunk",
                                    extra={
                                        "provider": self.provider,
                                        "stream_id": stream_id,
                                    },
                                )

                        elif delta_type == "input_json_delta":
                            partial_json = delta.get("partial_json", "") or ""
                            if partial_json == "":
                                continue
                            if index not in tool_blocks:
                                tool_blocks[index] = {
                                    "id": None,
                                    "name": "",
                                    "arguments": "",
                                }
                            block = tool_blocks[index]
                            block["arguments"] = str(block.get("arguments", "")) + str(
                                partial_json
                            )
                            fn = StreamingFunctionCall(
                                name=None,
                                arguments=str(partial_json),
                            )
                            stc = StreamingToolCall(
                                index=index,
                                id=block.get("id"),
                                type="function",
                                function=fn,
                            )
                            tc_dict = stc.model_dump(exclude_none=True)
                            chunk = self.create_normalized_chunk(
                                content="",
                                metadata={
                                    "model": model,
                                    "id": message_id,
                                    "index": index,
                                    "tool_calls": [tc_dict],
                                },
                                is_empty=False,
                                stream_id=stream_id,
                            )
                            if self.validate_chunk(chunk):
                                emitted_any = True
                                yield chunk
                            else:
                                logger.warning(
                                    "Dropping invalid tool input chunk",
                                    extra={
                                        "provider": self.provider,
                                        "stream_id": stream_id,
                                    },
                                )

                    elif event_type == "content_block_stop":
                        # Content block ended
                        # No action needed - just marks end of a content block
                        pass

                    elif event_type == "message_delta":
                        # Message-level delta (contains stop_reason, usage, etc.)
                        delta = event_data.get("delta", {})
                        stop_reason = delta.get("stop_reason")

                        # Map stop_reason to finish_reason
                        finish_reason = self._map_stop_reason(stop_reason)

                        # Extract usage if present
                        usage = event_data.get("usage")

                        # Emit chunk with finish_reason
                        if finish_reason:
                            chunk = self.create_normalized_chunk(
                                content="",
                                metadata={
                                    "model": model,
                                    "id": message_id,
                                    "finish_reason": finish_reason,
                                },
                                is_done=True,
                                is_empty=True,
                                stream_id=stream_id,
                            )

                            # Add usage if present
                            if usage:
                                chunk.usage = usage

                            if self.validate_chunk(chunk):
                                emitted_any = True
                                yield chunk
                            else:
                                logger.warning(
                                    "Dropping invalid finish chunk",
                                    extra={
                                        "provider": self.provider,
                                        "stream_id": stream_id,
                                    },
                                )

                    elif event_type == "message_stop":
                        # Message completed - emit final done marker
                        done_chunk = SentinelManager.create_done_chunk()

                        # Preserve stream_id and metadata
                        if stream_id:
                            done_chunk.stream_id = stream_id
                            done_chunk.metadata["stream_id"] = stream_id

                        done_chunk.metadata["provider"] = self.provider

                        if model:
                            done_chunk.metadata["model"] = model

                        if message_id:
                            done_chunk.metadata["id"] = message_id

                        emitted_any = True
                        yield done_chunk

                    elif event_type == "ping":
                        # Ping event - ignore
                        pass

                    elif event_type == "error":
                        # Error event
                        error_data = event_data.get("error", {})
                        error_type = error_data.get("type", "unknown")
                        error_message = error_data.get("message", "Unknown error")

                        # Create error exception and handle it
                        error = Exception(f"{error_type}: {error_message}")
                        error_chunk = await handle_streaming_error(
                            error, stream_id, self.provider
                        )
                        yield error_chunk
                        return

                    else:
                        # Unknown event type - log and skip
                        logger.warning(
                            "Unknown Anthropic event type",
                            extra={
                                "provider": self.provider,
                                "event_type": event_type,
                            },
                        )

        except Exception as e:
            if not emitted_any:
                raise
            # Emit error chunk
            error_chunk = await handle_streaming_error(e, stream_id, self.provider)
            yield error_chunk

    def _parse_sse_events(self, sse_data: str) -> list[SSEEvent]:
        """Parse Anthropic SSE format data into events.

        Anthropic uses event-based SSE format:
        event: message_start
        data: {"type":"message_start","message":{...}}

        Args:
            sse_data: Raw SSE data string

        Returns:
            List of SSEEvent objects.
        """
        events: list[SSEEvent] = []

        # Split by double newline to get individual events
        raw_events = sse_data.split("\n\n")

        for raw_event in raw_events:
            if not raw_event.strip():
                continue

            # Handle both \n\n and \r\n\r\n separators
            raw_event = raw_event.replace("\r\n", "\n")

            # Parse event and data lines
            lines = raw_event.split("\n")
            event_type: str | None = None
            data_lines: list[str] = []

            for line in lines:
                line = line.strip()

                if line.startswith("event:"):
                    # Extract event type
                    event_type = line[6:].strip()

                elif line.startswith("data:"):
                    # Extract data content
                    data_content = line[5:].strip()
                    data_lines.append(data_content)

            if not data_lines:
                continue

            data_str = " ".join(data_lines)

            try:
                event_data = json.loads(data_str)
            except json.JSONDecodeError as e:
                logger.warning(
                    "Failed to parse Anthropic event data as JSON",
                    exc_info=True,
                    extra={
                        "provider": self.provider,
                        "event_type": event_type,
                        "error": str(e),
                        "data_preview": data_str[:200] if data_str else "",
                    },
                )
                continue

            resolved_event_type = event_type
            if not resolved_event_type and isinstance(event_data, dict):
                top = event_data.get("type")
                if isinstance(top, str) and top.strip():
                    resolved_event_type = top.strip()

            if not resolved_event_type:
                continue

            events.append(
                SSEEvent(event_type=resolved_event_type, event_data=event_data)
            )

        return events

    def _map_stop_reason(self, stop_reason: str | None) -> str | None:
        """Map Anthropic stop_reason to OpenAI-style finish_reason.

        Args:
            stop_reason: Anthropic stop_reason value

        Returns:
            Mapped finish_reason value
        """
        if stop_reason is None:
            return None

        # Map Anthropic stop reasons to OpenAI finish reasons
        mapping = {
            "end_turn": "stop",
            "max_tokens": "length",
            "stop_sequence": "stop",
            "tool_use": "tool_calls",
        }

        return mapping.get(stop_reason, stop_reason)
