from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Lock for protecting global singleton initialization
_global_init_lock = threading.Lock()

# Maximum number of reasoning chunks to prevent unbounded memory growth
# 1000 chunks at ~100 bytes each = ~100KB per stream
_MAX_REASONING_CHUNKS = 1000

# Maximum number of content chunks to prevent unbounded memory growth
# 10000 chunks at ~100 bytes each = ~1MB per stream
# This is higher than reasoning chunks because content chunks are the main payload
_MAX_CONTENT_CHUNKS = 10000

# Maximum number of detected tool calls to prevent unbounded memory growth
# 1000 tool calls at ~200 bytes each = ~200KB per stream
_MAX_DETECTED_TOOL_CALLS = 1000

# Maximum number of extracted tool calls to prevent unbounded memory growth
# 1000 tool calls at ~200 bytes each = ~200KB per stream
_MAX_EXTRACTED_TOOL_CALLS = 1000


@dataclass
class StreamBufferState:
    """Accumulated content buffer for a streaming session."""

    chunks: deque[str] = field(default_factory=deque)
    encoded_chunks: deque[bytes] = field(default_factory=deque)
    chunk_lengths: deque[int] = field(default_factory=deque)
    reasoning_chunks: deque[str] = field(default_factory=deque)
    byte_length: int = 0
    truncation_logged: bool = False
    metadata_snapshot: dict[str, Any] = field(default_factory=dict)
    completed: bool = False
    has_sent_content: bool = False
    last_accessed: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def append_reasoning_chunk(self, chunk: str) -> None:
        """Append a reasoning chunk with size limit enforcement.

        Args:
            chunk: Reasoning chunk text to append

        Thread-safety: Acquires lock to prevent concurrent deque mutations
        from multiple async tasks or threads.
        """
        with self._lock:
            self.reasoning_chunks.append(chunk)
            # Enforce size limit to prevent unbounded memory growth
            while len(self.reasoning_chunks) > _MAX_REASONING_CHUNKS:
                self.reasoning_chunks.popleft()
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Evicted oldest reasoning chunk (max_chunks=%d reached)",
                        _MAX_REASONING_CHUNKS,
                    )

    def append_content_chunk(
        self, chunk_text: str, encoded_chunk: bytes, content_length: int
    ) -> None:
        """Append a content chunk with size limit enforcement.

        This method enforces size limits on chunks, encoded_chunks, and chunk_lengths
        deques to prevent unbounded memory growth when streams never complete.

        Args:
            chunk_text: The text content chunk
            encoded_chunk: The encoded bytes chunk
            content_length: The length of the encoded chunk

        Thread-safety: Acquires lock to prevent concurrent deque mutations
        from multiple async tasks or threads.
        """
        with self._lock:
            self.chunks.append(chunk_text)
            self.encoded_chunks.append(encoded_chunk)
            self.chunk_lengths.append(content_length)
            self.byte_length += content_length

            # Enforce size limit to prevent unbounded memory growth
            # Remove oldest chunks when limit is exceeded
            while len(self.chunks) > _MAX_CONTENT_CHUNKS:
                self.chunks.popleft()
                self.encoded_chunks.popleft()
                old_length = self.chunk_lengths.popleft()
                self.byte_length -= old_length
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Evicted oldest content chunk (max_chunks=%d reached, "
                        "removed %d bytes)",
                        _MAX_CONTENT_CHUNKS,
                        old_length,
                    )


@dataclass
class ToolCallBufferState:
    """Shared tool-call lifecycle state for a streaming session."""

    pending_text: str = ""
    detected_calls: list[dict[str, Any]] = field(default_factory=list)
    detected_signatures: set[str] = field(default_factory=set)
    processed_signatures: set[str] = field(default_factory=set)
    detected_canonical_ids: set[str] = field(default_factory=set)
    loop_cursor: int = 0
    reactor_cursor: int = 0
    allowed_tools: list[str] | None = None
    tracked_tags: set[str] = field(default_factory=set)
    # Flag to track if a tool call has been detected in this stream
    # Used to prevent immediate stop without content issues
    tool_call_detected: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def append_detected_call(self, tool_call: dict[str, Any]) -> None:
        """Append a detected tool call with size limit enforcement.

        Args:
            tool_call: Tool call dictionary to append

        Thread-safety: Acquires lock to prevent concurrent list mutations
        from multiple async tasks or threads.
        """
        with self._lock:
            self.detected_calls.append(tool_call)
            # Enforce size limit to prevent unbounded memory growth
            while len(self.detected_calls) > _MAX_DETECTED_TOOL_CALLS:
                self.detected_calls.pop(0)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Evicted oldest detected tool call (max_calls=%d reached)",
                        _MAX_DETECTED_TOOL_CALLS,
                    )


@dataclass
class JsonRepairBufferState:
    """Shared JSON repair state for a streaming session."""

    buffer: str = ""
    brace_level: int = 0
    in_string: bool = False
    json_started: bool = False


@dataclass
class VTCBufferState:
    """VTC (Virtual Tool Calling) buffer state for XML tool call processing.

    This state is used by VTC pre/post processors to:
    - Buffer streaming content until complete XML patterns are detected
    - Track extracted tool calls for the core pipeline
    - Store allowed tools whitelist for filtering
    """

    pending_text: str = ""
    extracted_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    allowed_tools: list[str] | None = None
    vtc_enabled: bool = False
    last_accessed: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def append_extracted_call(self, tool_call: dict[str, Any]) -> None:
        """Append an extracted tool call with size limit enforcement.

        Args:
            tool_call: Tool call dictionary to append

        Thread-safety: Acquires lock to prevent concurrent list mutations
        from multiple async tasks or threads.
        """
        with self._lock:
            self.extracted_tool_calls.append(tool_call)
            # Enforce size limit to prevent unbounded memory growth
            while len(self.extracted_tool_calls) > _MAX_EXTRACTED_TOOL_CALLS:
                self.extracted_tool_calls.pop(0)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Evicted oldest extracted tool call (max_calls=%d reached)",
                        _MAX_EXTRACTED_TOOL_CALLS,
                    )


@dataclass
class StreamContextState:
    """Composite state shared across streaming processors."""

    content: StreamBufferState = field(default_factory=StreamBufferState)
    tool_calls: ToolCallBufferState = field(default_factory=ToolCallBufferState)
    json_repair: JsonRepairBufferState = field(default_factory=JsonRepairBufferState)
    vtc: VTCBufferState = field(default_factory=VTCBufferState)
    execute_fragments: dict[str, str] = field(default_factory=dict)
    last_accessed: float = field(default_factory=time.time)


class StreamingContextRegistry:
    """Shared registry for per-stream buffering and metadata.

    Implements lazy TTL cleanup: expired states are removed automatically
    when accessing the registry, preventing memory leaks when processing stops.
    Also enforces a maximum number of states to prevent unbounded growth even
    if cleanup doesn't run frequently.
    """

    # Maximum number of stream states to prevent unbounded memory growth
    # This prevents accumulation when many streams are created but never accessed again
    _MAX_STREAM_STATES = 10000

    def __init__(self, state_ttl_seconds: int = 300) -> None:
        self._ttl_seconds = state_ttl_seconds
        self._states: dict[str, StreamContextState] = {}
        self._lock = threading.Lock()

    def get_content_state(self, stream_id: str) -> StreamBufferState:
        with self._lock:
            self._maybe_cleanup_expired()
            state = self._get_state(stream_id)
            now = time.time()
            state.last_accessed = now
            state.content.last_accessed = now
            return state.content

    def get_tool_call_buffer(self, stream_id: str) -> ToolCallBufferState:
        with self._lock:
            self._maybe_cleanup_expired()
            state = self._get_state(stream_id)
            state.last_accessed = time.time()
            return state.tool_calls

    def get_json_repair_buffer(self, stream_id: str) -> JsonRepairBufferState:
        with self._lock:
            self._maybe_cleanup_expired()
            state = self._get_state(stream_id)
            state.last_accessed = time.time()
            return state.json_repair

    def get_vtc_buffer(self, stream_id: str) -> VTCBufferState:
        """Get the VTC buffer state for a stream.

        Args:
            stream_id: The stream identifier.

        Returns:
            VTCBufferState for the stream.
        """
        with self._lock:
            self._maybe_cleanup_expired()
            state = self._get_state(stream_id)
            now = time.time()
            state.last_accessed = now
            state.vtc.last_accessed = now
            return state.vtc

    def get_stream_state(self, stream_id: str) -> StreamContextState:
        with self._lock:
            self._maybe_cleanup_expired()
            state = self._get_state(stream_id)
            state.last_accessed = time.time()
            return state

    def get_fragment(self, stream_id: str, namespace: str) -> str:
        with self._lock:
            self._maybe_cleanup_expired()
            state = self._get_state(stream_id)
            state.last_accessed = time.time()
            return state.execute_fragments.get(namespace, "")

    def set_fragment(self, stream_id: str, namespace: str, value: str) -> None:
        with self._lock:
            self._maybe_cleanup_expired()
            state = self._get_state(stream_id)
            state.last_accessed = time.time()
            if value:
                state.execute_fragments[namespace] = value
            elif namespace in state.execute_fragments:
                del state.execute_fragments[namespace]
                self._maybe_drop_stream(stream_id, state)

    def clear_content_state(self, stream_id: str) -> None:
        with self._lock:
            state = self._states.get(stream_id or "anonymous-stream")
            if state is None:
                return
            state.content = StreamBufferState()
            self._maybe_drop_stream(stream_id, state)

    def clear_tool_call_buffer(self, stream_id: str) -> None:
        with self._lock:
            state = self._states.get(stream_id)
            if state is None:
                return
            state.tool_calls = ToolCallBufferState()
            self._maybe_drop_stream(stream_id, state)

    def clear_json_repair_buffer(self, stream_id: str) -> None:
        with self._lock:
            state = self._states.get(stream_id)
            if state is None:
                return
            state.json_repair = JsonRepairBufferState()
            self._maybe_drop_stream(stream_id, state)

    def clear_vtc_buffer(self, stream_id: str) -> None:
        """Clear the VTC buffer state for a stream.

        Args:
            stream_id: The stream identifier.
        """
        with self._lock:
            state = self._states.get(stream_id)
            if state is None:
                return
            state.vtc = VTCBufferState()
            self._maybe_drop_stream(stream_id, state)

    def clear_fragment(self, stream_id: str, namespace: str) -> None:
        with self._lock:
            state = self._states.get(stream_id)
            if state is None:
                return
            if namespace in state.execute_fragments:
                del state.execute_fragments[namespace]
            self._maybe_drop_stream(stream_id, state)

    def _maybe_cleanup_expired(self) -> None:
        """Lazy cleanup: remove expired states if any exist.

        This is called automatically on every access to ensure expired states
        are cleaned up even when processing stops, preventing memory leaks.
        Must be called with lock held.
        """
        if not self._states:
            return

        now = time.time()
        expired = [
            stream_id
            for stream_id, state in self._states.items()
            if now - state.last_accessed > self._ttl_seconds
        ]
        for stream_id in expired:
            self._states.pop(stream_id, None)

    def cleanup_expired(self) -> None:
        """Remove stream states that exceeded the TTL.

        This method is kept for explicit cleanup calls, but cleanup now
        happens automatically via _maybe_cleanup_expired() on access.
        """
        with self._lock:
            self._maybe_cleanup_expired()

    def reset_content_states(self) -> None:
        """Reset only the content buffers (used by tests)."""
        with self._lock:
            for stream_id, state in list(self._states.items()):
                state.content = StreamBufferState()
                self._maybe_drop_stream(stream_id, state)

    def reset(self) -> None:
        with self._lock:
            self._states.clear()

    def _get_state(self, stream_id: str) -> StreamContextState:
        key = stream_id or "anonymous-stream"
        state = self._states.get(key)
        if state is None:
            # Enforce max states limit before adding new state
            if len(self._states) >= self._MAX_STREAM_STATES:
                # Evict oldest expired states first
                self._maybe_cleanup_expired()
                # If still at limit, evict oldest by last_accessed
                if len(self._states) >= self._MAX_STREAM_STATES:
                    oldest_key = min(
                        self._states.items(), key=lambda x: x[1].last_accessed
                    )[0]
                    self._states.pop(oldest_key, None)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Evicted oldest stream state %s (max_stream_states=%d reached)",
                            oldest_key,
                            self._MAX_STREAM_STATES,
                        )
            state = StreamContextState()
            self._states[key] = state
        return state

    def _maybe_drop_stream(self, stream_id: str, state: StreamContextState) -> None:
        if not stream_id:
            stream_id = "anonymous-stream"

        if (
            self._is_content_empty(state.content)
            and state.tool_calls.pending_text == ""
            and not state.json_repair.json_started
            and state.vtc.pending_text == ""
            and not state.vtc.extracted_tool_calls
            and not state.execute_fragments
            and not state.tool_calls.tracked_tags  # Don't drop if tags are tracked
        ):
            self._states.pop(stream_id, None)

    @staticmethod
    def _is_content_empty(content: StreamBufferState) -> bool:
        return (
            not content.chunks
            and not content.reasoning_chunks
            and content.byte_length == 0
            and not content.metadata_snapshot
            and not content.completed
        )


_GLOBAL_REGISTRY: StreamingContextRegistry | None = None


def set_global_streaming_context_registry(
    registry: StreamingContextRegistry,
) -> None:
    global _GLOBAL_REGISTRY
    _GLOBAL_REGISTRY = registry


def get_global_streaming_context_registry() -> StreamingContextRegistry:
    """Get the global StreamingContextRegistry singleton.

    Thread-safe: uses lock to prevent race condition where multiple threads
    could create multiple instances simultaneously.
    """
    global _GLOBAL_REGISTRY
    with _global_init_lock:
        if _GLOBAL_REGISTRY is None:
            _GLOBAL_REGISTRY = StreamingContextRegistry()
        return _GLOBAL_REGISTRY
