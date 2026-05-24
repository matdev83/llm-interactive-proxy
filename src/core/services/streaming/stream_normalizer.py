from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from uuid import uuid4

from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)
from src.core.interfaces.streaming_response_processor_interface import (
    CancelCallback,
    StreamItem,
)
from src.core.interfaces.streaming_response_processor_interface import (
    IStreamNormalizer as IProcessingStreamNormalizer,
)

logger = logging.getLogger(__name__)


class StreamNormalizer(IProcessingStreamNormalizer):
    """A service that normalizes streaming responses by applying a series of stream processors."""

    def __init__(self, processors: Sequence[IStreamProcessor] | None = None) -> None:
        """Initializes the StreamNormalizer.

        Args:
            processors: An optional sequence of IStreamProcessor instances to apply.
        """
        self._processors = list(processors) if processors is not None else []

    def reset(self) -> None:
        """Reset any stateful processors prior to processing a new stream."""
        for processor in self._processors:
            reset_method = getattr(processor, "reset", None)
            if callable(reset_method):
                try:
                    reset_method()
                except (RuntimeError, ValueError, TypeError):
                    # Common exceptions from processor reset operations
                    # RuntimeError: from processor state management issues
                    # ValueError: from invalid state transitions
                    # TypeError: from type mismatch in reset implementation
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to reset stream processor %s: %s",
                            type(processor).__name__,
                            "reset method raised exception",
                            exc_info=True,
                        )

    async def process_stream(
        self,
        stream: AsyncIterator[StreamItem],
        output_format: str = "bytes",
        cancel_callback: CancelCallback | None = None,
    ) -> AsyncGenerator[StreamingContent | bytes, None]:
        """Process a stream and convert to the desired output format.

        Args:
            stream: The input stream to process.
            output_format: The desired output format ("bytes" or "objects").
            cancel_callback: Optional callback to cancel upstream streaming.

        Yields:
            An async iterator of the processed stream in the requested format.
        """
        # Reset all processors before processing a new stream to ensure
        # per-stream state isolation (Requirement 7.5)
        #
        # FIX: Removed self.reset() call because StreamNormalizer is registered as a Singleton.
        # Calling reset() here wipes state for ALL concurrent streams in shared processors
        # (like ToolCallRepairProcessor -> StreamingContextRegistry).
        # Processors must be session-aware and manage state per-stream instead of relying on reset.
        # self.reset()

        stream_id = uuid4().hex

        async for chunk in stream:
            # If chunk is already StreamingContent, use it directly
            # Otherwise, convert using from_raw (which handles transport-neutral formats only)
            # Provider-specific formats should be normalized by provider normalizers before reaching here
            if isinstance(chunk, StreamingContent):
                content = chunk
            else:
                # Convert raw chunk to StreamingContent
                # Note: This should only receive transport-neutral formats.
                # Provider-specific formats (Anthropic events, Gemini JSON-lines) should
                # be normalized by provider normalizers before reaching this point.
                content = StreamingContent.from_raw(chunk)
            is_keepalive = bool(content.metadata.get("_keepalive"))

            # Ensure a stable identifier for this stream so that stateful processors
            # can keep their buffers isolated from other concurrent streams.
            metadata = content.metadata
            if "stream_id" not in metadata:
                metadata["stream_id"] = stream_id
            else:
                metadata["stream_id"] = str(metadata["stream_id"])

            # Skip empty chunks unless they are explicit keepalives.
            # Keepalives intentionally carry no user-visible content but must be
            # forwarded to prevent client-side timeouts during upstream waits.
            if content.is_empty and not content.is_done and not is_keepalive:
                continue

            # Apply processors in sequence
            for processor in self._processors:
                if cancel_callback is not None and hasattr(
                    processor, "cancel_callback"
                ):
                    try:
                        processor.cancel_callback = cancel_callback  # type: ignore[attr-defined]
                    except (AttributeError, TypeError, ValueError):
                        # Exceptions when setting cancel_callback on processor
                        # AttributeError: if cancel_callback is a read-only property
                        # TypeError: if type mismatch in assignment
                        # ValueError: if assignment validation fails
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Failed to set cancel_callback on processor %s",
                                type(processor).__name__,
                                exc_info=True,
                            )
                content = await processor.process(content)

                # Skip if processor made it empty (unless it's a keepalive)
                if content.is_empty and not content.is_done and not is_keepalive:
                    break

            # Yield if still has content or is done marker
            if not content.is_empty or content.is_done or is_keepalive:
                if output_format == "bytes":
                    yield content.to_bytes()
                elif output_format == "objects":
                    yield content
                else:
                    raise ValueError(f"Unsupported output_format: {output_format}")
