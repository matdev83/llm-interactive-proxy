"""Adapter for ToolCallBufferState to IToolCallBufferState interface."""

from __future__ import annotations

from src.core.domain.chat import ToolCall
from src.core.interfaces.tool_call_buffer_state import IToolCallBufferState
from src.core.services.streaming.stream_context_registry import ToolCallBufferState


class StreamBufferAdapter(IToolCallBufferState):
    """Adapter that wraps ToolCallBufferState to implement IToolCallBufferState.

    This adapter provides a clean interface boundary between the tool-call reactor
    subsystem and the streaming context registry, preserving dependency direction
    (interfaces don't import services).

    The adapter maps the concrete ToolCallBufferState semantics to the abstract
    interface:
    - consume_new_reactor_calls() consumes from detected_calls[reactor_cursor:]
      and advances reactor_cursor
    - is_processed() checks if a signature is in processed_signatures set
    - mark_processed() adds signatures to processed_signatures set
    """

    def __init__(self, buffer_state: ToolCallBufferState) -> None:
        """Initialize the adapter with a concrete buffer state.

        Args:
            buffer_state: The concrete ToolCallBufferState to wrap.
        """
        self._buffer_state = buffer_state

    def consume_new_reactor_calls(self) -> list[ToolCall]:
        """Return newly detected tool calls for the reactor and advance the cursor.

        Consumes tool calls from detected_calls starting at reactor_cursor and
        advances the cursor to mark them as consumed. Converts dict tool calls
        to ToolCall domain models.

        Returns:
            List of ToolCall objects that are newly available for reactor processing.
            Returns an empty list if no new calls are available or if the cursor
            has already consumed all detected calls.
        """
        if not self._buffer_state.detected_calls:
            return []

        if self._buffer_state.reactor_cursor >= len(self._buffer_state.detected_calls):
            return []

        # Consume calls from cursor position to end
        calls_dict = self._buffer_state.detected_calls[
            self._buffer_state.reactor_cursor :
        ]
        # Advance cursor to mark calls as consumed
        self._buffer_state.reactor_cursor = len(self._buffer_state.detected_calls)

        # Convert dict tool calls to ToolCall domain models
        tool_calls: list[ToolCall] = []
        for call_dict in calls_dict:
            try:
                if isinstance(call_dict, ToolCall):
                    tool_calls.append(call_dict)
                elif isinstance(call_dict, dict):
                    tool_calls.append(ToolCall(**call_dict))
                else:
                    # Try to convert using model_dump if available
                    if hasattr(call_dict, "model_dump"):
                        call_dict_converted = call_dict.model_dump()
                        tool_calls.append(ToolCall(**call_dict_converted))
                    else:
                        # Fallback: try direct conversion
                        tool_calls.append(ToolCall(**dict(call_dict)))
            except Exception:
                # Skip tool calls that can't be converted
                # This matches fail-open behavior from existing code
                continue

        return tool_calls

    def is_processed(self, signature: str) -> bool:
        """Check if a tool call signature has already been processed.

        Checks whether a signature exists in the processed_signatures set,
        indicating that the tool call has already been processed by the reactor.

        Args:
            signature: The signature string identifying the tool call to check.

        Returns:
            True if the signature has been processed, False otherwise.
        """
        return signature in self._buffer_state.processed_signatures

    def mark_processed(self, signature: str) -> None:
        """Record that a tool call signature was processed by the reactor.

        Adds the signature to the processed_signatures set to prevent duplicate
        processing within the same stream.

        Args:
            signature: The signature string identifying the processed tool call.
        """
        self._buffer_state.processed_signatures.add(signature)
