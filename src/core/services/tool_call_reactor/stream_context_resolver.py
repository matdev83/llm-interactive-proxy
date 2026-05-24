"""Stream context resolver for tool-call reactor subsystem.

This module implements DI-first stream identification and buffer state resolution
without requiring global mutable state. It matches the behavior of the existing
tool-call reactor middleware while using injected dependencies.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.tool_call_buffer_state import IToolCallBufferState
from src.core.interfaces.tool_call_stream_context_resolver_interface import (
    IToolCallStreamContextResolver,
)
from src.core.services.streaming.stream_context_registry import (
    StreamingContextRegistry,
    ToolCallBufferState,
)
from src.core.services.tool_call_reactor.stream_buffer_adapter import (
    StreamBufferAdapter,
)

logger = logging.getLogger(__name__)


class ToolCallStreamContextResolver(IToolCallStreamContextResolver):
    """Resolves stream context and buffer state for tool-call processing.

    This resolver provides DI-first access to stream identifiers and tool-call
    buffer state. It matches the behavior of the existing middleware's stream
    key and buffer state resolution logic, but uses injected StreamingContextRegistry
    instead of global state access.

    The resolver supports degraded mode when buffer state is unavailable, allowing
    the subsystem to operate safely without crashing requests.
    """

    def __init__(self, registry: StreamingContextRegistry) -> None:
        """Initialize the resolver with an injected registry.

        Args:
            registry: The StreamingContextRegistry to use for buffer state lookup.
                Must be injected via DI (not accessed globally).
        """
        self._registry = registry

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
        # Priority 1: Response metadata
        metadata = getattr(response, "metadata", None)
        if isinstance(metadata, dict):
            candidate = metadata.get("stream_id") or metadata.get("id")
            if isinstance(candidate, str) and candidate:
                return candidate

        # Priority 2: Context identifiers
        if isinstance(context, dict):
            candidate = context.get("stream_id") or context.get("response_stream_id")
            if isinstance(candidate, str) and candidate:
                return candidate

        # Priority 3: Session ID fallback
        if session_id:
            return session_id

        # Priority 4: Anonymous stream fallback
        return "anonymous-stream"

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
        # Degraded mode: no context
        if context is None:
            return None

        # Priority 1: Check context for direct buffer state
        candidate = context.get("tool_call_buffer_state")
        if isinstance(candidate, ToolCallBufferState):
            return StreamBufferAdapter(candidate)

        # Priority 2: Use registry with stream identifier
        # Determine stream identifier from context or fall back to stream_key
        stream_identifier = (
            context.get("stream_id") or context.get("response_stream_id") or stream_key
        )

        # Degraded mode: anonymous stream or empty identifier
        if not stream_identifier or stream_identifier == "anonymous-stream":
            return None

        try:
            buffer_state = self._registry.get_tool_call_buffer(str(stream_identifier))
            return StreamBufferAdapter(buffer_state)
        except Exception as e:
            # Fail-open: log and return None for degraded mode
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to resolve buffer state for stream %s: %s",
                    stream_identifier,
                    e,
                    exc_info=True,
                )
            return None
