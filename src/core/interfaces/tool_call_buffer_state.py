"""
Abstract buffer-state contract for tool-call reactor subsystem.

This module defines an abstract interface for accessing streaming tool-call buffer
state. This abstraction preserves dependency direction by allowing interfaces to
depend on abstractions rather than concrete service-layer types.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.chat import ToolCall


class IToolCallBufferState(ABC):
    """Abstract view over per-stream tool-call buffering state.

    This interface provides access to buffered tool calls detected during
    streaming responses. It abstracts over the concrete ToolCallBufferState
    implementation to preserve dependency direction (interfaces don't import
    services).

    The buffer maintains a cursor (reactor_cursor) that tracks which tool calls
    have been consumed by the reactor subsystem. New tool calls are consumed
    via consume_new_reactor_calls(), processed signatures are checked via
    is_processed(), and recorded via mark_processed().
    """

    @abstractmethod
    def consume_new_reactor_calls(self) -> list[ToolCall]:
        """Return newly detected tool calls for the reactor and advance the cursor.

        This method returns tool calls that have been detected since the last
        call to this method (based on the internal cursor position). After
        returning the calls, the cursor is advanced to mark them as consumed.

        Returns:
            List of ToolCall objects that are newly available for reactor processing.
            Returns an empty list if no new calls are available or if the cursor
            has already consumed all detected calls.
        """

    @abstractmethod
    def mark_processed(self, signature: str) -> None:
        """Record that a tool call signature was processed by the reactor.

        This method marks a tool call as processed to prevent duplicate processing
        within the same stream. The signature should match the format used by
        build_tool_call_signature() from the lifecycle registry.

        Args:
            signature: The signature string identifying the processed tool call.
        """

    @abstractmethod
    def is_processed(self, signature: str) -> bool:
        """Check if a tool call signature has already been processed.

        This method checks whether a tool call signature has been marked as processed
        within the buffer state. This is used to prevent duplicate processing of
        the same tool call within a stream.

        Args:
            signature: The signature string identifying the tool call to check.

        Returns:
            True if the signature has been processed, False otherwise.
        """
