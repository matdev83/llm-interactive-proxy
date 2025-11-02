import logging
import time
from collections import deque
from dataclasses import dataclass, field

from src.core.ports.streaming import IStreamProcessor, StreamingContent
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

        if content.is_empty and not content.is_done:
            # Preserve metadata/usage even when the chunk has no text so downstream
            # processors (e.g., usage accounting) still receive the updated values.
            return StreamingContent(
                content="",
                is_done=False,
                is_cancellation=content.is_cancellation,
                metadata=content.metadata,
                usage=content.usage,
                raw_data=content.raw_data,
            )

        # Add content to buffer and update byte length incrementally
        if content.content:
            # OPTIMIZATION: Encode content ONCE and cache both string and bytes
            encoded_content = content.content.encode("utf-8")
            content_length = len(encoded_content)

            state.chunks.append(content.content)
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
            self._states.pop(stream_id, None)
            return StreamingContent(
                content=final_content,
                is_done=True,
                metadata=content.metadata,
                usage=content.usage,
                raw_data=content.raw_data,
            )
        else:
            # Persist state for the next chunk
            self._states[stream_id] = state
            return StreamingContent(
                content="",
                metadata=content.metadata,
                usage=content.usage,
                raw_data=content.raw_data,
            )
