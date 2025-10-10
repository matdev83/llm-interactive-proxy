import logging
from collections import deque

from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)

logger = logging.getLogger(__name__)


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
        self._buffer: deque[str] = deque()
        self._buffer_byte_length = 0
        self._max_buffer_bytes = max_buffer_bytes
        self._truncation_logged = False

    def reset(self) -> None:
        """Reset the internal buffer so stale content does not leak between streams."""
        self._buffer.clear()
        self._buffer_byte_length = 0
        self._truncation_logged = False

    async def process(self, content: StreamingContent) -> StreamingContent:
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
            self._buffer.append(content.content)
            self._buffer_byte_length += len(content.content.encode("utf-8"))

        # Enforce buffer size limit to prevent unbounded memory growth
        if self._buffer_byte_length > self._max_buffer_bytes:
            if not self._truncation_logged:
                logger.warning(
                    f"ContentAccumulationProcessor buffer exceeded {self._max_buffer_bytes} bytes "
                    f"(current: {self._buffer_byte_length} bytes). Truncating to most recent content to prevent memory leak."
                )
                self._truncation_logged = True

            # Remove chunks from the left until we're under the limit
            while self._buffer and self._buffer_byte_length > self._max_buffer_bytes:
                removed_chunk = self._buffer.popleft()
                self._buffer_byte_length -= len(removed_chunk.encode("utf-8"))

        if content.is_done or content.is_cancellation:
            # Join all buffer chunks into final content
            final_content = "".join(self._buffer)
            self.reset()
            return StreamingContent(
                content=final_content,
                is_done=True,
                metadata=content.metadata,
                usage=content.usage,
                raw_data=content.raw_data,
            )
        else:
            return StreamingContent(
                content="",
                metadata=content.metadata,
                usage=content.usage,
                raw_data=content.raw_data,
            )
