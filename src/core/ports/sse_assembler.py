"""
SSE Assembler for streaming pipeline.

This module provides the SSEAssembler class that converts StreamingContent
to Server-Sent Events (SSE) format for client transmission.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.ports.streaming_contracts import (
    IStreamAssembler,
    SentinelManager,
    StreamingContent,
)
from src.core.ports.streaming_metrics import get_metrics_instance

logger = logging.getLogger(__name__)


class SSEAssembler(IStreamAssembler):
    """Assembler that converts StreamingContent to SSE format.

    This assembler handles the final conversion from internal StreamingContent
    representation to Server-Sent Events (SSE) format suitable for client
    transmission. It adds proper SSE framing (data: prefix and \\n\\n) and
    emits the final [DONE] sentinel using SentinelManager.
    """

    async def assemble_stream(
        self, stream: AsyncIterator[StreamingContent], format: str = "sse"
    ) -> AsyncIterator[bytes]:
        """Convert StreamingContent to SSE format.

        This method processes a stream of StreamingContent chunks and converts
        them to SSE format. It ensures proper framing and emits a final [DONE]
        marker using SentinelManager.

        Args:
            stream: Stream of StreamingContent chunks
            format: Output format (currently only "sse" is supported)

        Yields:
            SSE-formatted bytes ready for client transmission

        Raises:
            ValueError: If format is not "sse"
        """
        if format != "sse":
            raise ValueError(f"Unsupported format: {format}. Only 'sse' is supported.")

        done_emitted = False
        last_stream_id: str | None = None
        metrics = get_metrics_instance()

        try:
            async for chunk in stream:
                current_stream_id = chunk.stream_id or chunk.metadata.get("stream_id")
                if current_stream_id:
                    last_stream_id = current_stream_id
                stream_id_for_metrics = current_stream_id or last_stream_id

                # Skip empty chunks unless they're done markers or have errors
                if chunk.is_empty and not chunk.is_done:
                    continue

                # Check if this is a done marker with error or cancellation information
                # These chunks need to be serialized with their metadata via to_bytes()
                has_error = (
                    chunk.metadata.get("finish_reason") == "error"
                    and "error" in chunk.metadata
                )
                has_cancellation = chunk.is_cancellation and chunk.content

                if chunk.is_done and (has_error or has_cancellation):
                    # Error or cancellation chunk - serialize with metadata
                    chunk_bytes = chunk.to_bytes()
                    metrics.increment_chunks_sent(stream_id_for_metrics)
                    metrics.increment_sentinels_emitted(stream_id_for_metrics)
                    if logger.isEnabledFor(TRACE_LEVEL):
                        logger.log(
                            TRACE_LEVEL,
                            "[STREAMING][SSE] Emitting terminal chunk for stream %s (error=%s cancellation=%s)",
                            stream_id_for_metrics,
                            has_error,
                            has_cancellation,
                        )
                    yield chunk_bytes
                    # Mark that we've emitted a done marker (these include [DONE])
                    done_emitted = True
                    break

                # Check if this is a simple done marker (no error, no cancellation)
                if SentinelManager.is_done_marker(chunk):
                    # Emit the standardized [DONE] marker
                    if not done_emitted:
                        yield SentinelManager.format_sse_done()
                        # Track sentinel emission
                        metrics.increment_sentinels_emitted(stream_id_for_metrics)
                        if logger.isEnabledFor(TRACE_LEVEL):
                            logger.log(
                                TRACE_LEVEL,
                                "[STREAMING][SSE] Emitting done sentinel for stream %s",
                                stream_id_for_metrics,
                            )
                        done_emitted = True
                    break

                # Convert chunk to bytes using StreamingContent's to_bytes method
                chunk_bytes = chunk.to_bytes()

                # Track chunk emission
                metrics.increment_chunks_sent(stream_id_for_metrics)

                # Yield the chunk
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "[STREAMING][SSE] Emitting chunk for stream %s (%s bytes)",
                        stream_id_for_metrics,
                        len(chunk_bytes),
                    )
                yield chunk_bytes

                # Yield control to event loop for responsiveness
                await asyncio.sleep(0)

        finally:
            # Ensure [DONE] is always emitted, even if stream ends unexpectedly
            if not done_emitted:
                yield SentinelManager.format_sse_done()
                sentinel_stream_id = last_stream_id or "anonymous-stream"
                metrics.increment_sentinels_emitted(sentinel_stream_id)
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "[STREAMING][SSE] Emitting fallback done sentinel for stream %s",
                        sentinel_stream_id,
                    )
