import logging
from collections import deque
from dataclasses import dataclass, field

from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)
from src.core.services.streaming.stream_utils import get_stream_id

logger = logging.getLogger(__name__)


@dataclass
class _StreamBufferState:
    chunks: deque[str] = field(default_factory=deque)
    byte_length: int = 0
    truncation_logged: bool = False


class ContentAccumulationProcessor(IStreamProcessor):
    """
    Stream processor that accumulates content from streaming chunks.

    This processor buffers all streaming content until the stream is complete,
    then returns the full accumulated content. A maximum buffer size is enforced
    to prevent unbounded memory growth from pathologically large streams.
    """

    def __init__(self, max_buffer_bytes: int = 10 * 1024 * 1024) -> None:
        """
        Initialize the content accumulation processor.

        Args:
            max_buffer_bytes: Maximum buffer size in bytes (default: 10MB).
        """
        self._max_buffer_bytes = max_buffer_bytes
        self._states: dict[str, _StreamBufferState] = {}

    def _get_state(self, stream_id: str) -> _StreamBufferState:
        state = self._states.get(stream_id)
        if state is None:
            state = _StreamBufferState()
            self._states[stream_id] = state
        return state

    def reset(self) -> None:
        """Reset the internal buffer so stale content does not leak between streams."""
        self._states.clear()

    async def process(self, content: StreamingContent) -> StreamingContent:
        stream_id = get_stream_id(content)
        state = self._get_state(stream_id)

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
            state.chunks.append(content.content)
            state.byte_length += len(content.content.encode("utf-8"))

        # Enforce buffer size limit to prevent unbounded memory growth
        if state.byte_length > self._max_buffer_bytes:
            if not state.truncation_logged:
                logger.warning(
                    f"ContentAccumulationProcessor buffer exceeded {self._max_buffer_bytes} bytes "
                    f"(current: {state.byte_length} bytes). Truncating to most recent content to prevent memory leak."
                )
                state.truncation_logged = True

            # Remove chunks from the left until we're under the limit
            while state.chunks and state.byte_length > self._max_buffer_bytes:
                removed_chunk = state.chunks.popleft()
                state.byte_length -= len(removed_chunk.encode("utf-8"))

        if content.is_done or content.is_cancellation:
            # Join all buffer chunks into final content
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
