"""
Non-streaming adapter for unified pipeline processing.

This module provides adapters that wrap non-streaming responses as single-chunk
streams, enabling a unified processing path where all responses flow through
the same middleware chain.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.ports.streaming_contracts import StreamingContent

logger = logging.getLogger(__name__)


class NonStreamingAdapter:
    """Adapts non-streaming responses to the streaming pipeline.

    This enables a unified processing path where non-streaming responses
    are treated as a single-chunk stream, processed through the same
    middleware chain, then unwrapped back to a single response.

    Benefits:
    - DRY: All middleware logic lives in one place
    - Consistent: Same processing guarantees for both modes
    - Maintainable: Changes only need to be made once
    """

    @staticmethod
    async def wrap_as_stream(
        response: Any,
        session_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamingContent]:
        """Wrap a non-streaming response as a single-chunk stream.

        Args:
            response: The complete response (dict, ProcessedResponse, or raw)
            session_id: Session identifier
            metadata: Additional metadata to attach

        Yields:
            A single StreamingContent chunk with is_done=True
        """
        content = _extract_content(response)
        usage = _extract_usage(response)
        raw_metadata = _extract_metadata(response)

        chunk_metadata: dict[str, Any] = {
            "session_id": session_id,
            "non_streaming": True,  # Key flag for processors to detect single-chunk mode
            **raw_metadata,
            **(metadata or {}),
        }

        # Preserve tool_calls if present in the response
        tool_calls = _extract_tool_calls(response)
        if tool_calls:
            chunk_metadata["tool_calls"] = tool_calls

        # Yield single chunk with all content and is_done=True
        yield StreamingContent(
            content=content,
            is_done=True,  # Single chunk = done immediately
            is_cancellation=False,
            metadata=chunk_metadata,
            usage=usage,
            raw_data=response,
        )

    @staticmethod
    async def unwrap_from_stream(
        stream: AsyncIterator[StreamingContent | ProcessedResponse | bytes],
    ) -> ProcessedResponse:
        """Unwrap a processed stream back to a single response.

        For non-streaming, we expect exactly one chunk with is_done=True.
        This collects the result and returns it as ProcessedResponse.

        Args:
            stream: Processed stream (should contain single chunk for non-streaming)

        Returns:
            ProcessedResponse with accumulated content
        """
        final_content = ""
        final_usage: dict[str, Any] | None = None
        final_metadata: dict[str, Any] = {}

        async for chunk in stream:
            if isinstance(chunk, bytes):
                # Handle bytes directly - decode and accumulate
                try:
                    final_content += chunk.decode("utf-8")
                except UnicodeDecodeError:
                    final_content += chunk.decode("latin-1")
            elif isinstance(chunk, StreamingContent):
                # Accumulate content (should be just one chunk for non-streaming)
                if chunk.content:
                    if isinstance(chunk.content, str):
                        final_content += chunk.content
                    elif isinstance(chunk.content, bytes):
                        try:
                            final_content += chunk.content.decode("utf-8")
                        except UnicodeDecodeError:
                            final_content += chunk.content.decode("latin-1")
                    elif isinstance(chunk.content, dict):
                        # For dict content, check for StopChunkWithUsage first
                        # to avoid leaking usage data into accumulated content
                        import json

                        from src.core.ports.streaming_contracts import (
                            StopChunkWithUsage,
                        )

                        if isinstance(chunk.content, StopChunkWithUsage):
                            # Don't accumulate stop chunks with usage - they should
                            # be handled separately as final chunks, not content.
                            # Extract and preserve usage data from the StopChunkWithUsage
                            # so it's available in the final response.
                            stop_chunk_usage = chunk.content.get("usage")
                            if stop_chunk_usage and isinstance(stop_chunk_usage, dict):
                                final_usage = stop_chunk_usage
                        else:
                            final_content += json.dumps(chunk.content)
                if chunk.usage:
                    final_usage = chunk.usage
                if chunk.metadata:
                    final_metadata.update(chunk.metadata)
            elif isinstance(chunk, ProcessedResponse):
                # Handle ProcessedResponse directly
                if chunk.content:
                    final_content += str(chunk.content)
                if chunk.usage:
                    final_usage = chunk.usage
                if chunk.metadata:
                    final_metadata.update(chunk.metadata)

        # Remove internal flags from output metadata
        final_metadata.pop("non_streaming", None)

        return ProcessedResponse(
            content=final_content,
            usage=final_usage,
            metadata=final_metadata,
        )


def _extract_content(response: Any) -> str:
    """Extract content from various response formats."""
    if isinstance(response, ProcessedResponse):
        return response.content or ""

    if isinstance(response, StreamingContent):
        content = response.content
        if isinstance(content, str):
            return content
        if isinstance(content, bytes):
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError:
                return content.decode("latin-1")
        if isinstance(content, dict):
            # Use safe_json_dumps to handle StopChunkWithUsage correctly
            from src.core.ports.streaming_contracts import StopChunkWithUsage

            return StopChunkWithUsage.safe_json_dumps(content)
        return str(content) if content else ""

    if isinstance(response, dict):
        # OpenAI-style response
        choices = response.get("choices", [])
        if choices and isinstance(choices, list) and len(choices) > 0:
            choice = choices[0]
            if isinstance(choice, dict):
                # Check for message.content (non-streaming)
                message = choice.get("message")
                if isinstance(message, dict):
                    message_content = message.get("content")
                    if message_content is not None:
                        return str(message_content)
                # Check for delta.content (streaming chunk)
                delta = choice.get("delta")
                if isinstance(delta, dict):
                    delta_content = delta.get("content")
                    if delta_content is not None:
                        return str(delta_content)
        # Direct content field
        if "content" in response:
            return str(response["content"]) if response["content"] else ""

    if hasattr(response, "content"):
        attr_content = getattr(response, "content", None)
        return str(attr_content) if attr_content else ""

    return str(response) if response else ""


def _extract_usage(response: Any) -> dict[str, Any] | None:
    """Extract usage from various response formats."""
    if isinstance(response, ProcessedResponse):
        return response.usage

    if isinstance(response, StreamingContent):
        return response.usage

    if isinstance(response, dict):
        usage = response.get("usage")
        if isinstance(usage, dict):
            return usage

    if hasattr(response, "usage"):
        usage = getattr(response, "usage", None)
        if isinstance(usage, dict):
            return usage

    return None


def _extract_metadata(response: Any) -> dict[str, Any]:
    """Extract metadata from various response formats."""
    if isinstance(response, ProcessedResponse):
        return dict(response.metadata) if response.metadata else {}

    if isinstance(response, StreamingContent):
        return dict(response.metadata) if response.metadata else {}

    if isinstance(response, dict):
        metadata: dict[str, Any] = {}
        # Extract common metadata fields
        for key in ["id", "model", "created", "object", "system_fingerprint"]:
            if key in response:
                metadata[key] = response[key]
        # Extract finish_reason from choices
        choices = response.get("choices", [])
        if choices and isinstance(choices, list) and len(choices) > 0:
            choice = choices[0]
            if isinstance(choice, dict):
                finish_reason = choice.get("finish_reason")
                if finish_reason:
                    metadata["finish_reason"] = finish_reason
        return metadata

    if hasattr(response, "metadata"):
        attr_metadata = getattr(response, "metadata", None)
        if isinstance(attr_metadata, dict):
            return dict(attr_metadata)

    return {}


def _extract_tool_calls(response: Any) -> list[dict[str, Any]] | None:
    """Extract tool_calls from various response formats."""
    if isinstance(response, ProcessedResponse):
        metadata = response.metadata or {}
        tool_calls = metadata.get("tool_calls")
        if isinstance(tool_calls, list):
            return tool_calls

    if isinstance(response, StreamingContent):
        tool_calls = response.metadata.get("tool_calls")
        if isinstance(tool_calls, list):
            return tool_calls

    if isinstance(response, dict):
        # Check in choices[0].message.tool_calls (OpenAI format)
        choices = response.get("choices", [])
        if choices and isinstance(choices, list) and len(choices) > 0:
            choice = choices[0]
            if isinstance(choice, dict):
                message = choice.get("message")
                if isinstance(message, dict):
                    tool_calls = message.get("tool_calls")
                    if isinstance(tool_calls, list):
                        return tool_calls
        # Check direct tool_calls field
        tool_calls = response.get("tool_calls")
        if isinstance(tool_calls, list):
            return tool_calls

    return None
