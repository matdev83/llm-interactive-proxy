"""Usage tracking wrapper implementation.

Wraps streams to track usage metrics including TTFT, TPS, and completion tokens.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from src.core.interfaces.stream_formatting_interface import IStreamFormattingService
from src.core.interfaces.usage_tracking_wrapper_interface import IUsageTrackingWrapper

if TYPE_CHECKING:
    from src.core.interfaces.usage_tracking_interface import IUsageTrackingService

logger = logging.getLogger(__name__)


class UsageTrackingWrapper(IUsageTrackingWrapper):
    """Wrapper for tracking usage metrics on streams."""

    def __init__(
        self,
        usage_tracking_service: IUsageTrackingService | None = None,
        stream_formatting_service: IStreamFormattingService | None = None,
    ) -> None:
        """Initialize the usage tracking wrapper.

        Args:
            usage_tracking_service: Service for recording usage metrics.
            stream_formatting_service: Service for validating completion tokens.
        """
        self._usage_service = usage_tracking_service
        self._stream_formatting_service = stream_formatting_service

    def _is_valid_completion_token(self, chunk: Any) -> bool:
        """Check if chunk contains valid completion content.

        Uses the stream formatting service if available, otherwise falls back
        to a simple check.
        """
        if self._stream_formatting_service:
            return self._stream_formatting_service.is_valid_completion_token(chunk)

        # Fallback: simple check when service not available
        from src.core.interfaces.response_processor_interface import ProcessedResponse

        content = chunk.content if isinstance(chunk, ProcessedResponse) else chunk
        if isinstance(content, bytes | bytearray):
            text = content.decode("utf-8", errors="ignore").strip()
            return bool(text) and text not in (
                "[DONE]",
                '["DONE"]',
                "data: [DONE]",
            )
        if isinstance(content, str):
            text = content.strip()
            return bool(text) and text not in (
                "[DONE]",
                '["DONE"]',
                "data: [DONE]",
            )
        if isinstance(content, dict):
            choices = content.get("choices", [])
            if choices:
                for choice in choices:
                    delta = choice.get("delta", {})
                    if delta.get("content") or delta.get("tool_calls"):
                        return True
            return bool(content.get("content") or content.get("text"))
        return bool(content)

    def wrap_stream_for_usage(
        self,
        stream: AsyncIterator[Any],
        ctp_record_id: str | None,
        ptb_record_id: str | None,
        start_time: float,
    ) -> AsyncIterator[Any]:
        """Wrap stream to track usage metrics.

        Tracks TTFT, duration, TPS, and final usage data.
        No-op when usage service is not available or both record IDs are None.
        """
        usage_service = self._usage_service

        if not usage_service or (not ctp_record_id and not ptb_record_id):
            return stream

        from src.core.interfaces.response_processor_interface import ProcessedResponse
        from src.core.ports.streaming_contracts import StopChunkWithUsage

        async def _usage_wrapper() -> AsyncIterator[Any]:
            accumulated_usage = None
            first_token_time: float | None = None
            end_time: float | None = None

            try:
                async for chunk in stream:
                    # Only set first_token_time on first VALID token
                    if first_token_time is None and self._is_valid_completion_token(
                        chunk
                    ):
                        first_token_time = time.time()

                    content = (
                        chunk.content if isinstance(chunk, ProcessedResponse) else chunk
                    )

                    if isinstance(content, StopChunkWithUsage):
                        accumulated_usage = content.get("usage")
                    elif isinstance(content, dict) and "usage" in content:
                        accumulated_usage = content["usage"]

                    if isinstance(chunk, ProcessedResponse) and chunk.usage:
                        accumulated_usage = chunk.usage

                    yield chunk

                # Record end time after stream completes
                end_time = time.time()
            finally:
                if accumulated_usage:
                    completion_tokens = accumulated_usage.get("completion_tokens", 0)
                    ttft_ms = (
                        (first_token_time - start_time) * 1000
                        if first_token_time
                        else None
                    )
                    duration_ms = (time.time() - start_time) * 1000

                    # Calculate stream TPS (tokens per second after first token)
                    stream_tps: float | None = None
                    if (
                        first_token_time is not None
                        and end_time is not None
                        and completion_tokens > 0
                    ):
                        stream_duration = end_time - first_token_time
                        if stream_duration > 0:
                            stream_tps = completion_tokens / stream_duration

                    # Calculate backend wait time (time until first token)
                    backend_wait_ms = ttft_ms  # Same as TTFT for streaming

                    try:
                        if ptb_record_id:
                            await usage_service.record_response(
                                record_id=ptb_record_id,
                                completion_tokens=completion_tokens,
                                backend_reported_usage=accumulated_usage,
                                http_status_code=200,
                                ttft_ms=ttft_ms,
                                stream_tps=stream_tps,
                                backend_wait_ms=backend_wait_ms,
                                total_duration_ms=duration_ms,
                            )

                        if ctp_record_id:
                            await usage_service.record_response(
                                record_id=ctp_record_id,
                                completion_tokens=completion_tokens,
                                backend_reported_usage=accumulated_usage,
                                http_status_code=200,
                                ttft_ms=ttft_ms,
                                stream_tps=stream_tps,
                                backend_wait_ms=backend_wait_ms,
                                total_duration_ms=duration_ms,
                            )
                    except Exception as e:
                        logger.error(
                            f"Failed to record stream usage: {e}", exc_info=True
                        )

        return _usage_wrapper()
