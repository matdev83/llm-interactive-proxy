import logging
from collections import deque

logger = logging.getLogger(__name__)


class ResponseBuffer:
    """Manages a sliding window buffer of response content."""

    def __init__(self, max_size: int = 2048):
        self.max_size = max_size
        self.buffer: deque[str] = deque()
        self.total_length = 0
        self.stored_length = 0

    def append(self, text: str) -> None:
        """Append text to the buffer and maintain sliding window."""
        if not text:
            return

        self.buffer.append(text)
        self.stored_length += len(text)
        self.total_length += len(text)  # total_length tracks all content ever added

        # Trim from the left if buffer exceeds max_size
        while self.stored_length > self.max_size and self.buffer:
            oldest_chunk = self.buffer[0]
            excess = self.stored_length - self.max_size

            if len(oldest_chunk) <= excess:
                # Remove entire chunk
                self.buffer.popleft()
                self.stored_length -= len(oldest_chunk)
            else:
                # Remove part of the chunk
                self.buffer[0] = oldest_chunk[excess:]
                self.stored_length -= excess
                break  # Buffer is now within max_size

    def get_content(self) -> str:
        """Get the current buffer content as a string."""
        return "".join(self.buffer)

    def get_recent_content(self, length: int) -> str:
        """Get the most recent content up to specified length."""
        content = self.get_content()
        return content[-length:] if len(content) > length else content

    def clear(self) -> None:
        """Clear the buffer."""
        self.buffer.clear()
        self.total_length = 0
        self.stored_length = 0

    def size(self) -> int:
        """Get current buffer size."""
        return self.stored_length
