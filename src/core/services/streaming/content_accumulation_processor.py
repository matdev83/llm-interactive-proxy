import hashlib
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from src.core.ports.streaming_contracts import IStreamProcessor, StreamingContent
from src.core.services.streaming.stream_utils import get_stream_id

logger = logging.getLogger(__name__)


@dataclass
class _StreamBufferState:
    chunks: deque[str] = field(default_factory=deque)
    # Cache encoded chunks and their lengths to avoid repeated UTF-8 encoding
    encoded_chunks: deque[bytes] = field(default_factory=deque)
    chunk_lengths: deque[int] = field(default_factory=deque)
    byte_length: int = 0
    truncation_logged: bool = False
    # Track when this state was last accessed for TTL cleanup
    last_accessed: float = field(default_factory=time.time)
    metadata_snapshot: dict[str, Any] = field(default_factory=dict)
    completed: bool = False


class ContentAccumulationProcessor(IStreamProcessor):
    """
    Stream processor that accumulates content from streaming chunks.

    This processor buffers all streaming content until the stream is complete,
    then returns the full accumulated content. A maximum buffer size is enforced
    to prevent unbounded memory growth from pathologically large streams.

    Fixes memory leak by implementing TTL cleanup of stale stream states that
    don't complete normally (e.g., due to network timeouts, connection failures).
    """

    def __init__(
        self,
        max_buffer_bytes: int = 10 * 1024 * 1024,
        state_ttl_seconds: int = 300,  # 5 minutes default TTL
    ) -> None:
        """
        Initialize the content accumulation processor.

        Args:
            max_buffer_bytes: Maximum buffer size in bytes (default: 10MB).
            state_ttl_seconds: Time-to-live for stream states in seconds (default: 300).
                              Stale states older than this will be automatically cleaned up.
        """
        self._max_buffer_bytes = max_buffer_bytes
        self._state_ttl_seconds = state_ttl_seconds
        self._states: dict[str, _StreamBufferState] = {}

    def _get_state(self, stream_id: str) -> _StreamBufferState:
        state = self._states.get(stream_id)
        if state is None:
            state = _StreamBufferState()
            self._states[stream_id] = state
        return state

    def _cleanup_stale_states(self) -> None:
        """Remove stream states that have expired due to TTL."""
        current_time = time.time()
        expired_stream_ids = []

        for stream_id, state in list(self._states.items()):
            if current_time - state.last_accessed > self._state_ttl_seconds:
                expired_stream_ids.append(stream_id)

        # Clean up expired states
        for stream_id in expired_stream_ids:
            del self._states[stream_id]
            logger.debug(
                "Cleaned up expired stream state for stream_id=%s due to TTL (%s seconds)",
                stream_id,
                self._state_ttl_seconds,
            )

    def reset(self) -> None:
        """Reset the internal buffer so stale content does not leak between streams."""
        self._states.clear()

    async def process(self, content: StreamingContent) -> StreamingContent:
        # Clean up stale states on each request to prevent memory leaks
        self._cleanup_stale_states()

        stream_id = get_stream_id(content)
        state = self._get_state(stream_id)

        # Update last accessed time for TTL tracking
        state.last_accessed = time.time()

        # Merge metadata so downstream processors have a holistic view
        if content.metadata:
            merged_metadata = dict(state.metadata_snapshot)
            merged_metadata.update(content.metadata)
            state.metadata_snapshot = merged_metadata
        elif not state.metadata_snapshot and content.metadata is not None:
            state.metadata_snapshot = dict(content.metadata)

        if stream_id and "stream_id" in state.metadata_snapshot:
            state.metadata_snapshot["stream_id"] = stream_id

        def _build_metadata() -> dict[str, Any]:
            if state.metadata_snapshot:
                return dict(state.metadata_snapshot)
            if content.metadata:
                return dict(content.metadata)
            return {}

        if state.completed:
            metadata_snapshot = dict(content.metadata or {})
            metadata_snapshot.pop("tool_calls", None)
            if content.is_done or content.is_cancellation:
                self._states.pop(stream_id, None)
            return StreamingContent(
                content=content.content or "",
                is_done=content.is_done,
                is_cancellation=content.is_cancellation,
                metadata=metadata_snapshot,
                usage=content.usage,
                raw_data=content.raw_data,
            )

        if content.is_empty and not content.is_done:
            # Preserve metadata/usage even when the chunk has no text so downstream
            # processors (e.g., usage accounting) still receive the updated values.
            return StreamingContent(
                content="",
                is_done=False,
                is_cancellation=content.is_cancellation,
                metadata=_build_metadata(),
                usage=content.usage,
                raw_data=content.raw_data,
            )

        # Add content to buffer and update byte length incrementally
        raw_chunk = content.content
        if raw_chunk:
            if isinstance(raw_chunk, bytes):
                chunk_text = raw_chunk.decode("utf-8", errors="ignore")
            elif isinstance(raw_chunk, str):
                chunk_text = raw_chunk
            else:
                chunk_text = json.dumps(raw_chunk)
            # OPTIMIZATION: Encode content ONCE and cache both string and bytes
            encoded_content = chunk_text.encode("utf-8")
            content_length = len(encoded_content)

            state.chunks.append(chunk_text)
            state.encoded_chunks.append(encoded_content)
            state.chunk_lengths.append(content_length)
            state.byte_length += content_length

        # Enforce buffer size limit to prevent unbounded memory growth
        if state.byte_length > self._max_buffer_bytes:
            if not state.truncation_logged:
                logger.warning(
                    f"ContentAccumulationProcessor buffer exceeded {self._max_buffer_bytes} bytes "
                    f"(current: {state.byte_length} bytes). Truncating to most recent content to prevent memory leak."
                )
                state.truncation_logged = True

            # Remove chunks from the left until we're under the limit
            # OPTIMIZATION: Use cached lengths instead of re-encoding
            while state.chunks and state.byte_length > self._max_buffer_bytes:
                state.chunks.popleft()
                state.encoded_chunks.popleft()
                removed_length = state.chunk_lengths.popleft()
                state.byte_length -= removed_length

        if content.is_done or content.is_cancellation:
            # OPTIMIZATION: Use cached string chunks for final assembly
            # We could use cached bytes and decode, but string join is already optimal for this use case
            final_content = "".join(state.chunks)
            metadata_out = _build_metadata()
            tool_calls = metadata_out.get("tool_calls")
            if isinstance(tool_calls, list):
                unique_calls: list[dict[str, Any]] = []
                seen_signatures: set[tuple[Any | None, str]] = set()
                for call in tool_calls:
                    if not isinstance(call, dict):
                        continue
                    function_block = call.get("function", {})
                    if not isinstance(function_block, dict):
                        continue
                    name = function_block.get("name")
                    args_raw = function_block.get("arguments")
                    normalized_args = self._normalize_tool_call_arguments(args_raw)
                    identifier = call.get("id") or name
                    if not identifier:
                        identifier = self._build_function_identifier(function_block)
                    signature = (identifier, normalized_args)
                    if signature in seen_signatures:
                        continue
                    seen_signatures.add(signature)
                    unique_calls.append(call)
                metadata_out["tool_calls"] = unique_calls
            metadata_out["accumulated_content"] = final_content
            state.chunks.clear()
            state.encoded_chunks.clear()
            state.chunk_lengths.clear()
            state.byte_length = 0
            state.truncation_logged = False
            state.metadata_snapshot = dict(metadata_out)
            state.completed = True
            return StreamingContent(
                content=final_content,
                is_done=True,
                metadata=metadata_out,
                usage=content.usage,
                raw_data=content.raw_data,
            )
        else:
            # Persist state for the next chunk
            self._states[stream_id] = state
            interim_metadata = dict(content.metadata)
            interim_metadata.pop("tool_calls", None)
            return StreamingContent(
                content="",
                metadata=interim_metadata,
                usage=content.usage,
                raw_data=content.raw_data,
            )

    @staticmethod
    def _normalize_tool_call_arguments(arguments: Any) -> str:
        """Normalize tool call arguments into a hashable representation."""
        if arguments is None:
            return ""
        if isinstance(arguments, str):
            try:
                return json.dumps(json.loads(arguments), sort_keys=True)
            except json.JSONDecodeError:
                return arguments.strip()
        if isinstance(arguments, dict | list):
            try:
                return json.dumps(arguments, sort_keys=True)
            except (TypeError, ValueError):
                return str(arguments)
        if isinstance(arguments, bytes | bytearray):
            return arguments.decode("utf-8", errors="ignore")
        return str(arguments)

    @staticmethod
    def _build_function_identifier(function_block: dict[str, Any]) -> str:
        """Generate a stable identifier for unnamed tool calls."""
        try:
            serialized = json.dumps(function_block, sort_keys=True)
        except (TypeError, ValueError):
            serialized = repr(function_block)
        digest = hashlib.sha256(serialized.encode("utf-8", "ignore")).hexdigest()
        return f"unnamed-{digest}"
