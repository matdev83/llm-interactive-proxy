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
from src.core.domain.translation_utils.openai_compat_ids import (
    sanitize_openai_compatible_sse_payload_inplace,
)
from src.core.ports.streaming_contracts import (
    IStreamAssembler,
    SentinelManager,
    StreamingContent,
)
from src.core.ports.streaming_metrics import (
    get_metrics_instance,
    get_sampler_instance,
)
from src.core.services.steering_leak_protection import get_steering_leak_protector

logger = logging.getLogger(__name__)


class SSEAssembler(IStreamAssembler):
    """Assembler that converts StreamingContent to SSE format.

    This assembler handles the final conversion from internal StreamingContent
    representation to Server-Sent Events (SSE) format suitable for client
    transmission. It adds proper SSE framing (data: prefix and \n\n) and
    emits the final [DONE] sentinel using SentinelManager.
    """

    def __init__(self, yield_interval: int = 100) -> None:
        """Initialize SSE assembler.

        Args:
            yield_interval: Number of chunks to batch before yielding to event loop.
        """
        self._yield_interval = yield_interval

    async def assemble_stream(  # noqa: C901
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
        chunk_count = 0
        metrics = get_metrics_instance()
        first_data_emitted = False

        # Track OpenAI-style stream termination semantics.
        # Some clients rely on a terminal JSON chunk with non-null finish_reason
        # (in addition to the [DONE] sentinel) to dispatch tool calls or close a turn.
        saw_openai_payload = False
        saw_finish_reason = False
        saw_tool_calls = False
        terminal_finish_emitted = False
        last_openai_payload: dict[str, Any] | None = None

        sampler = get_sampler_instance()
        sampling_decided = False
        should_sample_stream = False
        sample_emitted = False

        def _iter_sse_events(payload: bytes) -> list[bytes]:
            if not payload:
                return []
            if b"\n\ndata:" not in payload and b"\n\nevent:" not in payload:
                return [payload]

            normalized = payload.replace(b"\r\n", b"\n")
            parts = normalized.split(b"\n\n")
            out: list[bytes] = []
            for part in parts:
                if not part.strip():
                    continue
                out.append(part + b"\n\n")
            return out

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

                # Skip empty chunks unless they're done markers or have errors.
                # Preserve whitespace-only chunks because models often stream
                # spaces as separate deltas and dropping them merges words.
                if (
                    chunk.is_empty
                    and not chunk.is_done
                    and not chunk.content
                    and not bool(chunk.metadata.get("_keepalive"))
                ):
                    continue

                # Check if this is a done marker with error or cancellation information
                # The serializer handles all error/cancellation serialization, so we
                # just need to track metrics and apply leak protection.
                has_error = (
                    chunk.metadata.get("finish_reason") == "error"
                    and "error" in chunk.metadata
                )
                has_cancellation = chunk.is_cancellation and chunk.content

                _ensure_stream_started(stream_id_for_metrics)

                if not first_data_emitted and not bool(
                    chunk.metadata.get("_keepalive")
                ):
                    first_data_emitted = True
                    elapsed = metrics.stop_timer(
                        stream_id_for_metrics, "time_to_first_chunk"
                    )
                    if elapsed is not None:
                        metrics.set_stream_metadata(
                            stream_id_for_metrics,
                            "time_to_first_chunk_seconds",
                            elapsed,
                        )

                elapsed_total = metrics.get_timer_elapsed(
                    stream_id_for_metrics, "total_duration"
                )
                if elapsed_total is not None:
                    metrics.set_stream_metadata(
                        stream_id_for_metrics,
                        "last_chunk_elapsed_seconds",
                        elapsed_total,
                    )

                # Convert chunk to bytes once for both paths
                chunk_bytes = chunk.to_bytes()

                if chunk.is_done and (has_error or has_cancellation):
                    # Error or cancellation chunk - serialize using serializer
                    # The serializer handles all framing and payload construction
                    protector = get_steering_leak_protector()
                    result = protector.sanitize_bytes(chunk_bytes)
                    chunk_bytes = result.data
                    if result.had_leak and logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "[STREAMING][SSE] Steering leak detected in terminal chunk "
                            "for stream %s - sanitized before sending to client",
                            stream_id_for_metrics,
                        )

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

                    for event_bytes in _iter_sse_events(chunk_bytes):
                        stripped = event_bytes.strip()
                        if stripped and stripped != b"data: [DONE]":
                            metrics.increment_chunks_sent(stream_id_for_metrics)
                        if stripped == b"data: [DONE]":
                            if not done_emitted:
                                metrics.increment_sentinels_emitted(
                                    stream_id_for_metrics
                                )
                                done_emitted = True
                            yield SentinelManager.format_sse_done()
                            break
                        yield event_bytes

                    done_emitted = True
                    break

                # CRITICAL: Apply steering leak protection as final safety net
                # This ensures internal steering data NEVER reaches clients, even if
                # upstream code fails to properly sanitize responses
                protector = get_steering_leak_protector()
                if protector.enabled:
                    result = protector.sanitize_bytes(chunk_bytes)
                    chunk_bytes = result.data
                    if result.had_leak and logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "[STREAMING][SSE] SECURITY: Sanitized leaked steering data "
                            "from outbound chunk for stream %s",
                            stream_id_for_metrics,
                        )

                # Log SSE output format at DEBUG level for diagnostic tracking
                from src.core.ports.streaming_contracts import StopChunkWithUsage

                is_stop_chunk_with_usage = isinstance(chunk.content, StopChunkWithUsage)
                has_usage = (
                    isinstance(chunk.content, dict) and "usage" in chunk.content
                ) or chunk.usage is not None
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "[STREAMING][SSE] Assembler serializing chunk: "
                        "stream_id=%s, is_done=%s, has_usage=%s, "
                        "is_stop_chunk_with_usage=%s, output_bytes=%d",
                        stream_id_for_metrics,
                        chunk.is_done,
                        has_usage,
                        is_stop_chunk_with_usage,
                        len(chunk_bytes),
                    )

                is_final_chunk = SentinelManager.is_done_marker(chunk)
                is_openai_stream = chunk.metadata.get("provider") == "openai" or (
                    isinstance(chunk.content, dict) and "choices" in chunk.content
                )

                for event_bytes in _iter_sse_events(chunk_bytes):
                    stripped = event_bytes.strip()
                    event_contains_done = b"data: [DONE]" in event_bytes

                    has_content = bool(
                        event_bytes and stripped and stripped != b"data: [DONE]"
                    )

                    if has_content:
                        # Best-effort detection of OpenAI-stream semantics from serialized bytes.
                        if is_openai_stream and b'"choices"' in event_bytes:
                            saw_openai_payload = True
                        if is_openai_stream and b'"tool_calls"' in event_bytes:
                            saw_tool_calls = True
                        if (
                            b'"finish_reason"' in event_bytes
                            and b'"finish_reason": null' not in event_bytes
                        ):
                            saw_finish_reason = True
                        if (
                            is_openai_stream
                            and b'"choices"' in event_bytes
                            and event_bytes.lstrip().startswith(b"data:")
                        ):
                            try:
                                raw_json = event_bytes.strip()
                                if raw_json.startswith(b"data: "):
                                    raw_json = raw_json[6:]
                                parsed = json.loads(raw_json.decode("utf-8"))
                                if isinstance(parsed, dict):
                                    last_openai_payload = parsed
                            except Exception:
                                # Parsing is best-effort; never break streaming.
                                pass

                        chunk_count += 1
                        _ensure_stream_started(stream_id_for_metrics)
                        metrics.increment_chunks_sent(stream_id_for_metrics)
                        if not sample_emitted:
                            _maybe_sample("chunk", event_bytes, stream_id_for_metrics)
                            sample_emitted = True

                        if logger.isEnabledFor(TRACE_LEVEL):
                            logger.log(
                                TRACE_LEVEL,
                                "[STREAMING][SSE] Emitting chunk for stream %s (%s bytes)",
                                stream_id_for_metrics,
                                len(event_bytes),
                            )
                        yield event_bytes

                        if (
                            not chunk.is_done
                            and chunk_count % self._yield_interval == 0
                        ):
                            await asyncio.sleep(0)

                    if event_contains_done:
                        # If we saw OpenAI-style JSON chunks but never observed a non-null
                        # finish_reason, inject a minimal terminal chunk before [DONE].
                        if (
                            saw_openai_payload
                            and not saw_finish_reason
                            and not terminal_finish_emitted
                        ):
                            inferred = "tool_calls" if saw_tool_calls else "stop"
                            terminal: dict[str, Any] = {
                                "object": "chat.completion.chunk",
                                "choices": [
                                    {"index": 0, "delta": {}, "finish_reason": inferred}
                                ],
                            }
                            if isinstance(last_openai_payload, dict):
                                for key in ("id", "model", "created"):
                                    if key in last_openai_payload:
                                        terminal[key] = last_openai_payload[key]

                            sanitize_openai_compatible_sse_payload_inplace(terminal)

                            terminal_bytes = (
                                f"data: {json.dumps(terminal)}\n\n".encode()
                            )
                            _ensure_stream_started(stream_id_for_metrics)
                            yield terminal_bytes
                            terminal_finish_emitted = True
                            saw_finish_reason = True

                        if not done_emitted:
                            yield SentinelManager.format_sse_done()
                            _ensure_stream_started(stream_id_for_metrics)
                            metrics.increment_sentinels_emitted(stream_id_for_metrics)
                            if logger.isEnabledFor(TRACE_LEVEL):
                                logger.log(
                                    TRACE_LEVEL,
                                    "[STREAMING][SSE] Emitting done sentinel for stream %s",
                                    stream_id_for_metrics,
                                )
                            done_emitted = True
                        break

                if done_emitted:
                    break

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

        except GeneratorExit:
            # Client disconnected - this is expected
            # Mark done_emitted=True to prevent finally block from trying to yield to a closed generator
            done_emitted = True
            raise
        except Exception:
            # An error occurred during iteration.
            # If we haven't emitted any data yet, we must NOT yield [DONE] in the finally block,
            # because yielding in finally suspended an active exception, which causes anext()
            # to return the yielded value instead of raising the exception.
            # This is critical for early error detection (prefetching) in the pipeline.
            if not first_data_emitted:
                done_emitted = True
            raise
        finally:
            # Ensure [DONE] is always emitted, even if stream ends unexpectedly
            # But NOT if the client disconnected (GeneratorExit)
            # And NOT if we're in an early error state (handled in except block above)
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
