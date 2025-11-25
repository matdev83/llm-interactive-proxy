from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


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
    last_accessed: float = field(default_factory=time.time)


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


@dataclass
class JsonRepairBufferState:
    """Shared JSON repair state for a streaming session."""

    buffer: str = ""
    brace_level: int = 0
    in_string: bool = False
    json_started: bool = False


@dataclass
class StreamContextState:
    """Composite state shared across streaming processors."""

    content: StreamBufferState = field(default_factory=StreamBufferState)
    tool_calls: ToolCallBufferState = field(default_factory=ToolCallBufferState)
    json_repair: JsonRepairBufferState = field(default_factory=JsonRepairBufferState)
    execute_fragments: dict[str, str] = field(default_factory=dict)
    last_accessed: float = field(default_factory=time.time)


class StreamingContextRegistry:
    """Shared registry for per-stream buffering and metadata."""

    def __init__(self, state_ttl_seconds: int = 300) -> None:
        self._ttl_seconds = state_ttl_seconds
        self._states: dict[str, StreamContextState] = {}
        self._lock = threading.Lock()

    def get_content_state(self, stream_id: str) -> StreamBufferState:
        with self._lock:
            state = self._get_state(stream_id)
            now = time.time()
            state.last_accessed = now
            state.content.last_accessed = now
            return state.content

    def get_tool_call_buffer(self, stream_id: str) -> ToolCallBufferState:
        with self._lock:
            state = self._get_state(stream_id)
            state.last_accessed = time.time()
            return state.tool_calls

    def get_json_repair_buffer(self, stream_id: str) -> JsonRepairBufferState:
        with self._lock:
            state = self._get_state(stream_id)
            state.last_accessed = time.time()
            return state.json_repair

    def get_stream_state(self, stream_id: str) -> StreamContextState:
        with self._lock:
            state = self._get_state(stream_id)
            state.last_accessed = time.time()
            return state

    def get_fragment(self, stream_id: str, namespace: str) -> str:
        with self._lock:
            state = self._get_state(stream_id)
            state.last_accessed = time.time()
            return state.execute_fragments.get(namespace, "")

    def set_fragment(self, stream_id: str, namespace: str, value: str) -> None:
        with self._lock:
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

    def clear_fragment(self, stream_id: str, namespace: str) -> None:
        with self._lock:
            state = self._states.get(stream_id)
            if state is None:
                return
            if namespace in state.execute_fragments:
                del state.execute_fragments[namespace]
            self._maybe_drop_stream(stream_id, state)

    def cleanup_expired(self) -> None:
        """Remove stream states that exceeded the TTL."""
        now = time.time()
        with self._lock:
            expired = [
                stream_id
                for stream_id, state in self._states.items()
                if now - state.last_accessed > self._ttl_seconds
            ]
            for stream_id in expired:
                self._states.pop(stream_id, None)

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
            and not state.execute_fragments
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
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = StreamingContextRegistry()
    return _GLOBAL_REGISTRY
