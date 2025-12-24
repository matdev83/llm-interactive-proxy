"""Response capture processor for ProxyMem feature.

Captures assistant responses from the streaming pipeline.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)

if TYPE_CHECKING:
    from src.core.memory.capture_middleware import MemoryCaptureMiddleware

logger = logging.getLogger(__name__)


class ResponseCaptureProcessor(IStreamProcessor):
    """Processor that captures responses for memory storage.

    This processor accumulates the full response content and captures it
    when the stream completes (is_done=True).
    """

    def __init__(
        self,
        memory_capture: MemoryCaptureMiddleware,
        session_id: str,
    ):
        """Initialize the response capture processor.

        Args:
            memory_capture: The memory capture middleware.
            session_id: The session identifier.
        """
        self._memory_capture = memory_capture
        self._session_id = session_id
        self._content_buffer: list[str] = []
        self._tool_calls: list[dict[str, Any]] = []
        self._model: str | None = None
        self._backend: str | None = None
        self._tokens_used: int | None = None
        self._lock = asyncio.Lock()

    async def process(self, content: StreamingContent) -> StreamingContent:
        """Process a chunk of content.

        Accumulates content and metadata. When the stream is done,
        captures the full interaction.

        Args:
            content: The content chunk to process.

        Returns:
            The original content chunk (unmodified).
        """
        async with self._lock:
            # Accumulate text content
            if isinstance(content.content, str) and content.content:
                self._content_buffer.append(content.content)

            # Accumulate tool calls
            tool_calls = content.metadata.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                self._tool_calls.extend(tool_calls)

            # Update metadata if present
            if content.metadata:
                if "model" in content.metadata:
                    self._model = str(content.metadata["model"])
                if "backend" in content.metadata:
                    self._backend = str(content.metadata["backend"])
                if "usage" in content.metadata:
                    usage = content.metadata["usage"]
                    if isinstance(usage, dict):
                        self._tokens_used = usage.get("total_tokens") or usage.get(
                            "completion_tokens"
                        )

            # Handle completion
            if content.is_done:
                full_content = "".join(self._content_buffer)
                try:
                    # We capture without awaiting if possible, but middleware is async
                    # Since process() is awaited, this is fine
                    await self._memory_capture.capture_response(
                        session_id=self._session_id,
                        content=full_content,
                        backend=self._backend,
                        model=self._model,
                        tokens_used=self._tokens_used,
                        tool_calls=self._tool_calls if self._tool_calls else None,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to capture response for session %s: %s",
                        self._session_id,
                        e,
                    )

        return content

    def reset(self) -> None:
        """Reset accumulated state."""
        self._content_buffer.clear()
        self._tool_calls.clear()
        self._model = None
        self._backend = None
        self._tokens_used = None
