from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from typing import Any
from uuid import uuid4

from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)
from src.core.interfaces.streaming_response_processor_interface import IStreamNormalizer

logger = logging.getLogger(__name__)


class StreamNormalizer(IStreamNormalizer):
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
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.debug(
                        "Failed to reset stream processor %s: %s",
                        type(processor).__name__,
                        exc,
                        exc_info=True,
                    )

    async def process_stream(
        self, stream: AsyncIterator[Any], output_format: str = "bytes"
    ) -> AsyncGenerator[StreamingContent | bytes, None]:
        """Process a stream and convert to the desired output format.

        Args:
            stream: The input stream to process.
            output_format: The desired output format ("bytes" or "objects").

        Yields:
            An async iterator of the processed stream in the requested format.
        """
        stream_id = uuid4().hex

        async for chunk in stream:
            # Convert raw chunk to StreamingContent
            content = StreamingContent.from_raw(chunk)

            # Ensure a stable identifier for this stream so that stateful processors
            # can keep their buffers isolated from other concurrent streams.
            metadata = content.metadata
            if "stream_id" not in metadata:
                metadata["stream_id"] = stream_id
            else:
                metadata["stream_id"] = str(metadata["stream_id"])

            # Skip empty chunks
            if content.is_empty and not content.is_done:
                continue

            # Apply processors in sequence
            for processor in self._processors:
                content = await processor.process(content)

                # Skip if processor made it empty
                if content.is_empty and not content.is_done:
                    break

            # Yield if still has content or is done marker
            if not content.is_empty or content.is_done:
                if output_format == "bytes":
                    yield content.to_bytes()
                elif output_format == "objects":
                    yield content
                else:
                    raise ValueError(f"Unsupported output_format: {output_format}")
