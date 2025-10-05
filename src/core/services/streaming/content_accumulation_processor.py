import logging

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
                If exceeded, the buffer is truncated to keep only the most recent content.
        """
        self._buffer = ""
        self._max_buffer_bytes = max_buffer_bytes
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

        self._buffer += content.content

        # Enforce buffer size limit to prevent unbounded memory growth
        buffer_size = len(self._buffer.encode("utf-8"))
        if buffer_size > self._max_buffer_bytes:
            if not self._truncation_logged:
                logger.warning(
                    f"ContentAccumulationProcessor buffer exceeded {self._max_buffer_bytes} bytes "
                    f"(current: {buffer_size} bytes). Truncating to most recent content to prevent memory leak."
                )
                self._truncation_logged = True

            # Keep only the most recent content that fits within the limit
            # Use a sliding window approach: keep the tail of the buffer
            excess_bytes = buffer_size - self._max_buffer_bytes
            # Estimate characters to remove (approximate, as UTF-8 can be 1-4 bytes per char)
            chars_to_remove = max(1, excess_bytes // 2)  # Conservative estimate
            self._buffer = self._buffer[chars_to_remove:]

            # Verify we're now under the limit, if not, be more aggressive
            while len(self._buffer.encode("utf-8")) > self._max_buffer_bytes:
                # Remove 10% more characters
                chars_to_remove = max(1, len(self._buffer) // 10)
                self._buffer = self._buffer[chars_to_remove:]

        if content.is_done:
            final_content = self._buffer
            self._buffer = ""
            self._truncation_logged = False  # Reset for next stream
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
