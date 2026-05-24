"""
Interface for resolving stream context in the tool-call reactor subsystem.

This module defines the interface for components that resolve stream identifiers
and buffer state for tool-call processing. The resolver supports DI-first access
to streaming state without requiring global mutable state.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.tool_call_buffer_state import IToolCallBufferState


class IToolCallStreamContextResolver(ABC):
    """Interface for resolving stream context and buffer state.

    This resolver provides DI-first access to stream identifiers and tool-call
    buffer state. It supports degraded mode when buffer state is unavailable,
    allowing the subsystem to operate safely without crashing requests.

    The resolver matches the behavior of the existing tool-call reactor middleware's
    stream key and buffer state resolution logic, but uses injected dependencies
    instead of global state access.
    """

    @abstractmethod
    def resolve_stream_key(
        self,
        session_id: str,
        context: dict[str, Any] | None,
        response: ProcessedResponse | Any,
    ) -> str:
        """Resolve stream key for lifecycle tracking.

        Resolves a stream identifier using the following priority order:
        1. Response metadata: metadata.get("stream_id") or metadata.get("id")
        2. Context: context.get("stream_id") or context.get("response_stream_id")
        3. Session ID fallback
        4. "anonymous-stream" as final fallback

        This matches the behavior of the existing middleware's _resolve_stream_key()
        method to ensure compatibility.

        Args:
            session_id: The session ID associated with the request
            context: Optional context dictionary (may be None for degraded mode)
            response: The processed response object (may have metadata attribute)

        Returns:
            A stream key string for lifecycle tracking. Never returns None or empty string.
        """

    @abstractmethod
    def resolve_buffer_state(
        self,
        context: dict[str, Any] | None,
        stream_key: str,
    ) -> IToolCallBufferState | None:
        """Resolve buffer state for tool-call buffering.

        Resolves tool-call buffer state using the following priority order:
        1. Check context.get("tool_call_buffer_state") (if ToolCallBufferState, wrap with adapter)
        2. Use injected registry with stream identifier
        3. Return None for degraded mode (non-streaming or missing context)

        This matches the behavior of the existing middleware's _resolve_buffer_state()
        method, but uses injected registry instead of global access.

        Args:
            context: Optional context dictionary (may be None for degraded mode)
            stream_key: The stream key to use for registry lookup

        Returns:
            An IToolCallBufferState adapter wrapping the buffer state, or None if
            buffer state is unavailable (degraded mode). Returns None gracefully
            without raising exceptions.
        """
