"""
Interface for tool-call deduplication in the tool-call reactor subsystem.

This module defines the interface for components that filter duplicate tool calls
and mark tool calls as processed to prevent re-execution loops.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.chat import ToolCall
from src.core.interfaces.tool_call_buffer_state import IToolCallBufferState


class IToolCallDeduplicator(ABC):
    """Interface for deduplicating tool calls and tracking processed state.

    This deduplicator ensures that tool calls are processed at most once per stream
    and marks them as processed to prevent re-execution loops. It integrates with
    both the lifecycle registry (for non-buffered calls) and buffer state (for
    buffered calls and processed marking).

    The deduplicator preserves behavior differences between streaming and non-streaming
    regarding lifecycle clearing and completion detection.
    """

    @abstractmethod
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
        - Already processed: skipped if signature is in buffer_state.processed_signatures

        Args:
            tool_calls: List of tool calls to filter (may include both buffered and non-buffered)
            stream_key: The stream key for lifecycle tracking
            buffer_state: Optional buffer state (None for degraded mode)
            is_streaming: Whether this is a streaming response

        Returns:
            List of tool calls that are new and should be processed. May be empty
            if all calls are duplicates or already processed.
        """

    @abstractmethod
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

    @abstractmethod
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
