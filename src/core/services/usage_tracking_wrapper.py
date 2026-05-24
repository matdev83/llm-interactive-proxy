"""Usage tracking wrapper implementation.

Wraps streams to track usage metrics including TTFT, TPS, and completion tokens.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from src.core.domain.translation_utils.processed_response_usage import (
    usage_summary_from_processed_response,
)
from src.core.domain.usage_summary import UsageSummary
from src.core.interfaces.response_processor_interface import ProcessedResponse
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
            choices_raw_value = content.get("choices", [])
            if isinstance(choices_raw_value, list) and choices_raw_value:
                for choice_item in choices_raw_value:
                    if not isinstance(choice_item, dict):
                        continue
                    delta_value = choice_item.get("delta", {})
                    if not isinstance(delta_value, dict):
                        continue
                    if delta_value.get("content") or delta_value.get("tool_calls"):
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

        async def _usage_wrapper() -> AsyncIterator[Any]:
            accumulated_usage: Any = None
            first_token_time: float | None = None
            end_time: float | None = None

            try:
                async for chunk in stream:
                    # Only set first_token_time on first VALID token
                    if first_token_time is None and self._is_valid_completion_token(
                        chunk
                    ):
                        first_token_time = time.time()

                    if isinstance(chunk, ProcessedResponse):
                        pr: ProcessedResponse | None = chunk
                    elif isinstance(chunk, dict):
                        pr = ProcessedResponse(content=chunk)
                    else:
                        pr = None

                    summary = (
                        usage_summary_from_processed_response(pr)
                        if pr is not None
                        else None
                    )
                    if summary is not None:
                        # Match legacy behavior: keep ``ProcessedResponse.usage`` objects
                        # intact so ``record_response`` still sees ``to_dict()``-style payloads
                        # with extensions when callers attached a ``UsageSummary`` directly.
                        # For usage parsed only from ``content["usage"]``, flatten to the
                        # legacy OpenAI-style dict shape (same as the pre-refactor path).
                        if isinstance(summary, UsageSummary):
                            if (
                                isinstance(chunk, ProcessedResponse)
                                and chunk.usage is summary
                            ):
                                accumulated_usage = summary
                            else:
                                accumulated_usage = summary.to_legacy_dict()
                        else:
                            accumulated_usage = summary

                    yield chunk

                # Record end time after stream completes
                end_time = time.time()
            finally:
                if accumulated_usage:
                    completion_tokens_raw = (
                        accumulated_usage.get("completion_tokens", 0)
                        if isinstance(accumulated_usage, dict)
                        else (
                            getattr(accumulated_usage, "completion_tokens", 0)
                            if hasattr(accumulated_usage, "completion_tokens")
                            else 0
                        )
                    )
                    completion_tokens = (
                        int(completion_tokens_raw)
                        if isinstance(completion_tokens_raw, int | float | str)
                        else 0
                    )
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
                            stream_tps = float(completion_tokens) / stream_duration

                    # Calculate backend wait time (time until first token)
                    backend_wait_ms = ttft_ms  # Same as TTFT for streaming

                    # Convert accumulated_usage to dict if needed
                    usage_dict: dict[str, Any] | None = None
                    if accumulated_usage is not None:
                        if isinstance(accumulated_usage, dict):
                            usage_dict = accumulated_usage
                        elif hasattr(accumulated_usage, "model_dump"):
                            usage_dict = accumulated_usage.model_dump()  # type: ignore[attr-defined]
                        elif hasattr(accumulated_usage, "to_dict"):
                            usage_dict = accumulated_usage.to_dict()  # type: ignore[attr-defined]
                        else:
                            usage_dict = {}

                    try:
                        if ptb_record_id:
                            await usage_service.record_response(
                                record_id=ptb_record_id,
                                completion_tokens=completion_tokens,
                                backend_reported_usage=usage_dict,
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
                                backend_reported_usage=usage_dict,
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
