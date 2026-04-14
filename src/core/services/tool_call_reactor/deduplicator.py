"""Tool-call deduplicator for tool-call reactor subsystem.

This module implements deduplication and processed marking for tool calls,
integrating with both the lifecycle registry and buffer state to prevent
duplicate processing and re-execution loops.
"""

from __future__ import annotations

import logging

from src.core.domain.chat import ToolCall
from src.core.interfaces.tool_call_buffer_state import IToolCallBufferState
from src.core.interfaces.tool_call_deduplicator_interface import (
    IToolCallDeduplicator,
)
from src.tool_call_loop.lifecycle_registry import (
    ToolCallLifecycleRegistry,
    build_reactor_processing_signature,
)

logger = logging.getLogger(__name__)


class ToolCallDeduplicator(IToolCallDeduplicator):
    """Deduplicates tool calls and tracks processed state.

    This deduplicator ensures that tool calls are processed at most once per stream
    and marks them as processed to prevent re-execution loops. It integrates with
    both the lifecycle registry (for non-buffered calls) and buffer state (for
    buffered calls and processed marking).

    The deduplicator preserves behavior differences between streaming and non-streaming
    regarding lifecycle clearing and completion detection.
    """

    def __init__(self, lifecycle_registry: ToolCallLifecycleRegistry) -> None:
        """Initialize the deduplicator with an injected lifecycle registry.

        Args:
            lifecycle_registry: The ToolCallLifecycleRegistry to use for tracking
                processed signatures. Must be injected via DI.
        """
        self._lifecycle_registry = lifecycle_registry

    async def filter_new_calls(
        self,
        tool_calls: list[ToolCall],
        stream_key: str,
        buffer_state: IToolCallBufferState | None,
        is_streaming: bool,
    ) -> list[ToolCall]:
        """Filter tool calls to only those that are new and should be processed.

        Filters tool calls based on:
        - Buffered calls: consumed via buffer_state.consume_new_reactor_calls()
          (already deduped by buffer cursor)
        - Non-buffered calls: checked against lifecycle registry with register_detection()
        - Already processed: skipped if signature is already processed in buffer state

        Args:
            tool_calls: List of tool calls to filter (non-buffered calls from response).
                Buffered calls are consumed from buffer_state if provided.
            stream_key: The stream key for lifecycle tracking
            buffer_state: Optional buffer state (None for degraded mode)
            is_streaming: Whether this is a streaming response

        Returns:
            List of tool calls that are new and should be processed. May be empty
            if all calls are duplicates or already processed.
        """
        new_calls: list[ToolCall] = []

        # Consume buffered calls if buffer state is available
        if buffer_state is not None:
            buffered_calls = buffer_state.consume_new_reactor_calls()
            new_calls.extend(buffered_calls)

        # Filter non-buffered calls against lifecycle registry
        for tool_call in tool_calls:
            # If name is missing during streaming, skip processing until it arrives.
            # This prevents "None:hash" signature collisions and useless reactor calls.
            if is_streaming and not tool_call.function.name:
                continue

            signature = build_reactor_processing_signature(
                tool_call.model_dump(), is_streaming=is_streaming
            )

            # Check if already processed in buffer state

            if buffer_state is not None and buffer_state.is_processed(signature):
                continue

            # Use namespaced signature for reactor to avoid collision with loop detection
            namespaced_signature = f"reactor:{signature}"

            # Check lifecycle registry for non-buffered calls
            is_new = await self._lifecycle_registry.register_detection(
                stream_key, namespaced_signature
            )
            if not is_new:
                continue

            new_calls.append(tool_call)

        return new_calls

    async def mark_processed(
        self,
        stream_key: str,
        signature: str,
        buffer_state: IToolCallBufferState | None,
    ) -> None:
        """Mark a tool call signature as processed.

        Marks a tool call as processed in both:
        - Lifecycle registry: prevents duplicate processing across streams
        - Buffer state: prevents reprocessing within the same stream

        Args:
            stream_key: The stream key for lifecycle tracking
            signature: The tool call signature to mark as processed
            buffer_state: Optional buffer state (None for degraded mode)
        """
        # Use namespaced signature for reactor
        namespaced_signature = f"reactor:{signature}"

        # Ensure state exists in lifecycle registry by registering detection first
        # This matches the existing middleware behavior where mark_processed is
        # called after register_detection
        await self._lifecycle_registry.register_detection(
            stream_key, namespaced_signature
        )

        # Mark in lifecycle registry (moves from inflight to processed)
        await self._lifecycle_registry.mark_processed(stream_key, namespaced_signature)

        # Mark in buffer state if available
        if buffer_state is not None:
            buffer_state.mark_processed(signature)

    async def is_processed(
        self,
        stream_key: str,
        signature: str,
    ) -> bool:
        """Check if a tool call signature has already been processed.

        Args:
            stream_key: The stream key for lifecycle tracking
            signature: The tool call signature to check

        Returns:
            True if the signature has been processed, False otherwise.
        """
        # Use namespaced signature for reactor
        namespaced_signature = f"reactor:{signature}"
        return await self._lifecycle_registry.is_processed(
            stream_key, namespaced_signature
        )
