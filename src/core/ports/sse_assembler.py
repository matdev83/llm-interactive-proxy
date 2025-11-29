"""
SSE Assembler for streaming pipeline.

This module provides the SSEAssembler class that converts StreamingContent
to Server-Sent Events (SSE) format for client transmission.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.ports.streaming_contracts import (
    IStreamAssembler,
    SentinelManager,
    StreamingContent,
)
from src.core.ports.streaming_metrics import (
    get_metrics_instance,
    get_sampler_instance,
)

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

        sampler = get_sampler_instance()
        sampling_decided = False
        should_sample_stream = False
        sample_emitted = False

        def _format_sample_payload(payload: Any) -> str:
            if isinstance(payload, bytes):
                try:
                    text_value = payload.decode("utf-8")
                except UnicodeDecodeError:
                    text_value = payload.decode("latin-1", errors="ignore")
            else:
                text_value = str(payload)
            if len(text_value) > 2000:
                text_value = f"{text_value[:2000]}…"
            return text_value

        def _maybe_sample(
            sample_type: str, payload: Any, stream_identifier: str | None
        ) -> None:
            nonlocal sampling_decided, should_sample_stream
            if not stream_identifier:
                return
            if not sampling_decided:
                should_sample_stream = sampler.should_sample()
                sampling_decided = True
            if not should_sample_stream:
                return
            sampler.add_sample(
                stream_identifier,
                sample_type,
                _format_sample_payload(payload),
            )

        started_stream_id: str | None = None
        generated_stream_id = f"anonymous-{uuid.uuid4().hex}"

        def _ensure_stream_started(target_stream_id: str | None) -> None:
            nonlocal started_stream_id
            if not target_stream_id:
                return
            if started_stream_id == target_stream_id:
                return
            metrics.start_stream(target_stream_id)
            started_stream_id = target_stream_id

        try:
            async for chunk in stream:
                current_stream_id = chunk.stream_id or chunk.metadata.get("stream_id")
                if current_stream_id:
                    last_stream_id = current_stream_id
                stream_id_for_metrics = current_stream_id or last_stream_id
                if stream_id_for_metrics is None:
                    stream_id_for_metrics = generated_stream_id
                    if last_stream_id is None:
                        last_stream_id = generated_stream_id

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
                    # Error or cancellation chunk - serialize with metadata. If the
                    # chunk serialized to only a sentinel, rebuild an error payload
                    # so clients see the failure instead of an empty stream.
                    chunk_bytes = chunk.to_bytes()
                    if (
                        has_error
                        and chunk_bytes.strip() == b"data: [DONE]"
                        and "error" in chunk.metadata
                    ):
                        error_payload = {
                            "choices": [{"delta": {}, "finish_reason": "error"}],
                            "error": chunk.metadata.get("error"),
                        }
                        for key in ("id", "model", "created"):
                            if key in chunk.metadata:
                                error_payload[key] = chunk.metadata[key]
                        chunk_bytes = (
                            f"data: {json.dumps(error_payload)}\n\ndata: [DONE]\n\n"
                        ).encode()
                    _ensure_stream_started(stream_id_for_metrics)
                    metrics.increment_chunks_sent(stream_id_for_metrics)
                    metrics.increment_sentinels_emitted(stream_id_for_metrics)
                    if has_error:
                        _maybe_sample(
                            "error_chunk",
                            chunk.metadata.get("error", chunk.content),
                            stream_id_for_metrics,
                        )
                    elif has_cancellation:
                        _maybe_sample(
                            "cancellation_chunk",
                            chunk.content or chunk.metadata,
                            stream_id_for_metrics,
                        )
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

                # Convert chunk to bytes using StreamingContent's to_bytes method
                chunk_bytes = chunk.to_bytes()

                # Log SSE output format at DEBUG level for diagnostic tracking
                from src.core.ports.streaming_contracts import StopChunkWithUsage

                is_stop_chunk_with_usage = isinstance(chunk.content, StopChunkWithUsage)
                has_usage = (
                    isinstance(chunk.content, dict) and "usage" in chunk.content
                ) or chunk.usage is not None
                logger.debug(
                    "[STREAMING][SSE] Assembler serializing chunk: "
                    "stream_id=%s, is_done=%s, has_usage=%s, "
                    "is_stop_chunk_with_usage=%s, output_bytes=%d",
                    stream_id_for_metrics,
                    chunk.is_done,
                    has_usage,
                    is_stop_chunk_with_usage,
                    len(chunk_bytes),
                )

                # Check if this is a done marker (but may still have content to emit)
                is_final_chunk = SentinelManager.is_done_marker(chunk)

                # Yield the chunk (only if it has content)
                # Skip empty chunks that are just done markers
                has_content = bool(
                    chunk_bytes
                    and chunk_bytes.strip()
                    and chunk_bytes.strip() != b"data: [DONE]"
                )

                # Check if chunk already contains [DONE] (from to_bytes() when is_done=True)
                chunk_contains_done = b"data: [DONE]" in chunk_bytes

                if has_content:
                    # Track chunk emission (only for chunks with actual content)
                    _ensure_stream_started(stream_id_for_metrics)
                    metrics.increment_chunks_sent(stream_id_for_metrics)
                    if not sample_emitted:
                        _maybe_sample("chunk", chunk_bytes, stream_id_for_metrics)
                        sample_emitted = True

                    if logger.isEnabledFor(TRACE_LEVEL):
                        logger.log(
                            TRACE_LEVEL,
                            "[STREAMING][SSE] Emitting chunk for stream %s (%s bytes)",
                            stream_id_for_metrics,
                            len(chunk_bytes),
                        )
                    yield chunk_bytes

                    # If chunk already contains [DONE], mark as emitted
                    if chunk_contains_done:
                        done_emitted = True
                        metrics.increment_sentinels_emitted(stream_id_for_metrics)

                # If this is the final chunk, emit [DONE] and stop
                if is_final_chunk:
                    if not done_emitted:
                        yield SentinelManager.format_sse_done()
                        metrics.increment_sentinels_emitted(stream_id_for_metrics)
                        if logger.isEnabledFor(TRACE_LEVEL):
                            logger.log(
                                TRACE_LEVEL,
                                "[STREAMING][SSE] Emitting done sentinel for stream %s",
                                stream_id_for_metrics,
                            )
                        done_emitted = True
                    break

                # Yield control to event loop for responsiveness
                await asyncio.sleep(0)

        finally:
            # Ensure [DONE] is always emitted, even if stream ends unexpectedly
            if not done_emitted:
                yield SentinelManager.format_sse_done()
                sentinel_stream_id = last_stream_id or generated_stream_id
                _ensure_stream_started(sentinel_stream_id)
                metrics.increment_sentinels_emitted(sentinel_stream_id)
                _maybe_sample(
                    "sentinel", SentinelManager.DONE_MARKER, sentinel_stream_id
                )
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "[STREAMING][SSE] Emitting fallback done sentinel for stream %s",
                        sentinel_stream_id,
                    )
