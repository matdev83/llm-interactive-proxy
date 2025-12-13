"""Stream formatting service implementation.

Converts domain chunks to SSE-encoded bytes and validates completion tokens.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from src.core.interfaces.stream_formatting_interface import IStreamFormattingService

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class StreamFormattingService(IStreamFormattingService):
    """Service for SSE stream formatting and token validation."""

    def stream_as_sse_bytes(self, stream: AsyncIterator[Any]) -> AsyncIterator[bytes]:
        """Convert domain chunks to SSE-encoded bytes.

        Accepts an async iterator that may yield ProcessedResponse, dict, str, or bytes
        and produces an async iterator of bytes suitable for wire capture and direct
        transport to clients.
        """
        from src.core.interfaces.response_processor_interface import ProcessedResponse
        from src.core.ports.streaming_contracts import (
            StopChunkWithUsage,
            StreamingContent,
        )

        async def _adapter() -> AsyncIterator[bytes]:
            done_sent = False
            async for chunk in stream:
                content = (
                    chunk.content if isinstance(chunk, ProcessedResponse) else chunk
                )
                metadata = (
                    chunk.metadata if isinstance(chunk, ProcessedResponse) else {}
                )

                # CRITICAL: Check for StopChunkWithUsage and convert to SSE properly
                # Use StreamingContent.to_bytes() which knows how to handle it correctly
                if isinstance(content, StopChunkWithUsage):
                    # Create StreamingContent and use its to_bytes() method
                    # which properly serializes StopChunkWithUsage with usage at top level
                    streaming_content = StreamingContent(
                        content=content,
                        is_done=True,
                        metadata=metadata,
                        usage=content.get("usage"),
                    )
                    yield streaming_content.to_bytes()
                    done_sent = True
                else:
                    yield self.format_chunk_as_sse(content)

                if self.chunk_signals_done(content, metadata):
                    done_sent = True
                    if isinstance(content, bytes | bytearray | str):
                        text_str = (
                            content.decode("utf-8", errors="ignore")
                            if isinstance(content, bytes | bytearray)
                            else content
                        )
                        stripped = text_str.strip()
                        if stripped in ("[DONE]", '["DONE"]'):
                            break
                        if stripped.startswith(("data: [DONE]", 'data: ["DONE"]')):
                            break
                    yield b"data: [DONE]\n\n"
                    break

            if not done_sent:
                yield b"data: [DONE]\n\n"

        return _adapter()

    def is_valid_completion_token(self, chunk: Any) -> bool:
        """Check if chunk contains valid completion content.

        A valid completion token is one that:
        - Is not empty or whitespace-only
        - Is not a [DONE] marker
        - Contains actual content (text delta or tool call)
        """
        from src.core.interfaces.response_processor_interface import ProcessedResponse

        # Extract content from ProcessedResponse if needed
        content = chunk.content if isinstance(chunk, ProcessedResponse) else chunk

        # Handle bytes
        if isinstance(content, bytes | bytearray):
            text = content.decode("utf-8", errors="ignore").strip()
            # Check for [DONE] markers
            if text in ("[DONE]", '["DONE"]', "data: [DONE]", 'data: ["DONE"]'):
                return False
            # Check for empty/keepalive
            if not text or text.startswith(":"):
                return False
            # SSE comments are keepalives
            if text.startswith("data:"):
                data_part = text[5:].strip()
                if not data_part or data_part in ("[DONE]", '["DONE"]'):
                    return False
            return True

        # Handle strings
        if isinstance(content, str):
            text = content.strip()
            if text in ("[DONE]", '["DONE"]', "data: [DONE]", 'data: ["DONE"]'):
                return False
            if not text or text.startswith(":"):
                return False
            if text.startswith("data:"):
                data_part = text[5:].strip()
                if not data_part or data_part in ("[DONE]", '["DONE"]'):
                    return False
            return True

        # Handle dict (JSON chunk)
        if isinstance(content, dict):
            # Check for actual content
            choices = content.get("choices", [])
            if choices:
                for choice in choices:
                    delta = choice.get("delta", {})
                    # Has actual text content
                    if delta.get("content"):
                        return True
                    # Has tool calls
                    if delta.get("tool_calls"):
                        return True
                    # Has function call
                    if delta.get("function_call"):
                        return True
            # Check for direct content field
            return bool(content.get("content") or content.get("text"))

        # For ProcessedResponse, check metadata for content
        if isinstance(chunk, ProcessedResponse):
            if chunk.metadata and chunk.metadata.get("tool_calls"):
                return True
            # Already extracted content above
            return bool(content)

        return False

    def format_chunk_as_sse(self, content: Any) -> bytes:
        """Format a single chunk as SSE bytes.

        Content that already begins with `data:` is passed through unchanged.
        Raw `[DONE]` / `["DONE"]` is normalized to `b"data: [DONE]\\n\\n"`.
        Otherwise returns bytes framed as `data: {payload}\\n\\n`.
        """
        if isinstance(content, bytes | bytearray):
            stripped_bytes = bytes(content).strip()
            if stripped_bytes.startswith(b"data:"):
                return bytes(content)
            if stripped_bytes in (b"[DONE]", b'["DONE"]'):
                return b"data: [DONE]\n\n"
            text_val = content.decode("utf-8", errors="replace")
            return f"data: {text_val}\n\n".encode()

        if isinstance(content, str):
            stripped_text = content.strip()
            if stripped_text.startswith("data:"):
                return content.encode("utf-8")
            if stripped_text in ("[DONE]", '["DONE"]'):
                return b"data: [DONE]\n\n"
            return f"data: {content}\n\n".encode()

        # Handle Pydantic models (like CanonicalStreamChunk) by converting to dict
        if hasattr(content, "model_dump") and callable(content.model_dump):
            return f"data: {json.dumps(content.model_dump())}\n\n".encode()

        if isinstance(content, dict):
            return f"data: {json.dumps(content)}\n\n".encode()

        # Fallback: try to JSON serialize, otherwise use str representation
        try:
            return f"data: {json.dumps(content)}\n\n".encode()
        except (TypeError, ValueError):
            return f"data: {content}\n\n".encode()

    def chunk_signals_done(self, content: Any, metadata: dict[str, Any] | None) -> bool:
        """Check if chunk signals stream completion.

        Detects completion signaled by:
        - Raw/sse `[DONE]` / `["DONE"]`
        - `metadata.finish_reason`
        - `content.metadata.finish_reason`
        - OpenAI-style `choices[*].finish_reason` / empty deltas with finish_reason
        """
        if isinstance(content, bytes | bytearray):
            text = content.decode("utf-8", errors="ignore").strip()
            if text == "[DONE]" or text.startswith("data: [DONE]"):
                return True
            if text == '["DONE"]' or text.startswith('data: ["DONE"]'):
                return True
        elif isinstance(content, str):
            stripped = content.strip()
            if stripped == "[DONE]" or stripped.startswith("data: [DONE]"):
                return True
            if stripped == '["DONE"]' or stripped.startswith('data: ["DONE"]'):
                return True

        if metadata and metadata.get("finish_reason"):
            if content is None or content == "":
                return True
            if isinstance(content, dict):
                choices = content.get("choices") or []
                if choices:
                    delta = (
                        choices[0].get("delta") if isinstance(choices[0], dict) else {}
                    )
                    if not delta or all(
                        not delta.get(key)
                        for key in (
                            "content",
                            "tool_calls",
                            "reasoning_content",
                            "reasoning",
                        )
                    ):
                        return True

        if isinstance(content, dict):
            content_metadata = content.get("metadata")
            if isinstance(content_metadata, dict) and content_metadata.get(
                "finish_reason"
            ):
                return True
            choices = content.get("choices")
            if isinstance(choices, list):
                for choice in choices:
                    if isinstance(choice, dict) and choice.get("finish_reason"):
                        return True

        return False
