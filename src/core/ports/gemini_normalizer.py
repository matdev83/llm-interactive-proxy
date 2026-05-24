"""
Gemini stream normalizer.

This module provides normalization of Gemini-specific streaming formats
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


class GeminiStreamNormalizer(BaseStreamNormalizer):
    """Normalizer for Gemini streaming responses.

    This normalizer handles Gemini's JSON-lines format:
    - Parses JSON-lines format (one JSON object per line)
    - Extracts text from candidates[0].content.parts
    - Maps function_call to tool_calls
    - Handles finishReason
    """

    def __init__(self) -> None:
        """Initialize the Gemini normalizer."""
        super().__init__(provider="gemini")

    async def normalize_stream(
        self, stream: AsyncIterator[object], provider: str
    ) -> AsyncIterator[StreamingContent]:
        """Convert Gemini-specific stream to StreamingContent.

        Args:
            stream: Raw stream from Gemini backend (opaque provider-specific data)
            provider: Provider name (should be "gemini")

        Yields:
            Normalized StreamingContent chunks
        """
        stream_id: str | None = None
        emitted_any = False

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

                # Parse JSON-lines format - may contain multiple JSON objects
                for json_obj in self._parse_json_lines(chunk_str):
                    # Extract stream_id from first chunk if available
                    if stream_id is None and "id" in json_obj:
                        stream_id = json_obj["id"]

                    # Convert to StreamingContent
                    normalized_chunk = self._normalize_chunk(json_obj, stream_id)
                    if normalized_chunk and self.validate_chunk(normalized_chunk):
                        emitted_any = True
                        yield normalized_chunk
                    elif normalized_chunk is not None:
                        logger.warning(
                            "Dropping invalid normalized Gemini chunk",
                            extra={"provider": self.provider, "stream_id": stream_id},
                        )

            # Emit final done marker
            done_chunk = SentinelManager.create_done_chunk()
            if stream_id:
                done_chunk.stream_id = stream_id
                done_chunk.metadata["stream_id"] = stream_id
            done_chunk.metadata["provider"] = self.provider
            emitted_any = True
            yield done_chunk

        except Exception as e:
            if not emitted_any:
                raise
            # Emit error chunk
            error_chunk = await handle_streaming_error(e, stream_id, self.provider)
            yield error_chunk

    def _parse_json_lines(self, data: str) -> list[dict[str, Any]]:
        """Parse JSON-lines format data into individual JSON objects.

        JSON-lines format is: one JSON object per line, separated by newlines.

        Args:
            data: Raw JSON-lines data string

        Returns:
            List of parsed JSON objects
        """
        json_objects: list[dict[str, Any]] = []

        # Split by newlines to get individual JSON objects
        lines = data.strip().split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            try:
                json_obj = json.loads(line)
                json_objects.append(json_obj)
            except json.JSONDecodeError as e:
                logger.warning(
                    "Failed to parse JSON line",
                    exc_info=True,
                    extra={
                        "provider": self.provider,
                        "error": str(e),
                        "line_preview": line[:200] if line else "",
                    },
                )
                continue

        return json_objects

    def _normalize_chunk(
        self, json_obj: dict[str, Any], stream_id: str | None
    ) -> StreamingContent | None:
        """Normalize a single Gemini chunk to StreamingContent.

        Args:
            json_obj: Parsed JSON object
            stream_id: Stream identifier

        Returns:
            Normalized StreamingContent or None if chunk should be skipped
        """
        # Extract candidates array
        candidates = json_obj.get("candidates", [])
        if not candidates:
            # Empty candidates - skip this chunk
            return None

        # Get first candidate (Gemini typically uses index 0)
        candidate = candidates[0]

        # Extract content from candidate
        content_obj = candidate.get("content", {})
        parts = content_obj.get("parts", [])

        # Build metadata
        metadata: dict[str, Any] = {
            "provider": self.provider,
        }

        # Add stream_id if available
        if stream_id:
            metadata["stream_id"] = stream_id

        # Add model if available
        if "modelVersion" in json_obj:
            metadata["model"] = json_obj["modelVersion"]

        # Add id if available
        if "id" in json_obj:
            metadata["id"] = json_obj["id"]

        # Add role if present in content
        if "role" in content_obj:
            metadata["role"] = content_obj["role"]

        # Extract finish_reason from finishReason
        finish_reason_raw = candidate.get("finishReason")
        finish_reason = self._map_finish_reason(finish_reason_raw)
        if finish_reason:
            metadata["finish_reason"] = finish_reason

        # Add index if available
        if "index" in candidate:
            metadata["index"] = candidate["index"]

        # Extract content and tool calls from parts
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        usage = json_obj.get("usage")

        for part in parts:
            # Extract text content
            if "text" in part:
                text_parts.append(part["text"])

            # Extract function_call and map to tool_calls
            if "functionCall" in part:
                function_call = part["functionCall"]
                tool_call = self._map_function_call_to_tool_call(function_call)
                if tool_call:
                    tool_calls.append(tool_call)

        # Build content_text efficiently from collected parts
        content_text = "".join(text_parts)

        # Add tool_calls to metadata if present
        if tool_calls:
            metadata["tool_calls"] = tool_calls

        # Determine if this is a done chunk
        is_done = finish_reason is not None

        # Determine if this is an empty chunk
        is_empty = not content_text and not tool_calls and not usage

        # If this is the terminal usage chunk with no text/tool calls, emit an
        # OpenAI-style payload so usage reaches the client.
        if is_done and usage and not content_text and not tool_calls:
            content_payload: dict[str, Any] = {
                "choices": [
                    {
                        "index": metadata.get("index", 0),
                        "delta": {"role": metadata.get("role", "assistant")},
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": usage,
            }
            if "model" in metadata:
                content_payload["model"] = metadata["model"]
            if "id" in metadata:
                content_payload["id"] = metadata["id"]

            # Use StopChunkWithUsage to ensure ContentAccumulationProcessor
            # correctly merges any buffered content into this final chunk.
            from src.core.ports.streaming_contracts import StopChunkWithUsage

            stop_chunk = StopChunkWithUsage(content_payload)

            return self.create_normalized_chunk(
                content=stop_chunk,
                metadata=metadata,
                is_done=True,
                is_empty=False,
                stream_id=stream_id,
            )

        # Create normalized chunk
        chunk = self.create_normalized_chunk(
            content=content_text,
            metadata=metadata,
            is_done=is_done,
            is_empty=is_empty,
            stream_id=stream_id,
        )

        # Preserve usage on terminal chunks that also carry content/tool calls
        if is_done and usage:
            chunk.metadata["usage"] = usage
            if isinstance(chunk.content, dict):
                chunk.content = dict(chunk.content)
                chunk.content["usage"] = usage

        return chunk

    def _map_finish_reason(self, finish_reason: str | None) -> str | None:
        """Map Gemini finishReason to OpenAI-style finish_reason.

        Args:
            finish_reason: Gemini finishReason value

        Returns:
            Mapped finish_reason value
        """
        if finish_reason is None:
            return None

        # Map Gemini finish reasons to OpenAI finish reasons
        mapping = {
            "STOP": "stop",
            "MAX_TOKENS": "length",
            "SAFETY": "content_filter",
            "RECITATION": "content_filter",
            "OTHER": "stop",
            "FINISH_REASON_UNSPECIFIED": None,
        }

        return mapping.get(finish_reason, finish_reason.lower())

    def _map_function_call_to_tool_call(
        self, function_call: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Map Gemini function_call to OpenAI-style tool_call.

        Args:
            function_call: Gemini function_call object

        Returns:
            Mapped tool_call object or None if invalid
        """
        # Extract function name
        name = function_call.get("name")
        if not name:
            logger.warning(
                "Function call missing name", extra={"provider": self.provider}
            )
            return None

        # Extract arguments
        args = function_call.get("args", {})

        # Convert args to JSON string
        try:
            args_json = json.dumps(args)
        except (TypeError, ValueError) as e:
            logger.warning(
                "Failed to serialize function call arguments",
                exc_info=True,
                extra={"provider": self.provider, "error": str(e)},
            )
            args_json = "{}"

        # Build OpenAI-style tool_call
        tool_call = {
            "id": function_call.get("id", f"call_{name}"),
            "type": "function",
            "function": {
                "name": name,
                "arguments": args_json,
            },
        }

        return tool_call
