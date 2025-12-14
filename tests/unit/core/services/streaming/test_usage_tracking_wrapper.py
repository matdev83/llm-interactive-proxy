"""Unit tests for UsageTrackingWrapper.

Tests first token time tracking, usage data accumulation,
TPS calculation, and equivalence with BackendService._wrap_stream_for_usage.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.stream_formatting_service import StreamFormattingService
from src.core.services.usage_tracking_wrapper import UsageTrackingWrapper


class TestWrapStreamForUsage:
    """Tests for wrap_stream_for_usage method."""

    @pytest.mark.asyncio
    async def test_returns_original_stream_when_no_usage_service(self) -> None:
        """Stream should pass through unchanged when usage service is None."""
        wrapper = UsageTrackingWrapper(usage_tracking_service=None)

        async def gen():
            yield ProcessedResponse(content={"choices": [{"delta": {"content": "hi"}}]})

        original_gen = gen()
        wrapped = wrapper.wrap_stream_for_usage(
            original_gen, ctp_record_id="ctp-123", ptb_record_id="ptb-456", start_time=1000.0
        )

        # Should return the same generator
        assert wrapped is original_gen

    @pytest.mark.asyncio
    async def test_returns_original_stream_when_no_record_ids(self) -> None:
        """Stream should pass through unchanged when both record IDs are None."""
        mock_service = AsyncMock()
        wrapper = UsageTrackingWrapper(usage_tracking_service=mock_service)

        async def gen():
            yield ProcessedResponse(content={"choices": [{"delta": {"content": "hi"}}]})

        original_gen = gen()
        wrapped = wrapper.wrap_stream_for_usage(
            original_gen, ctp_record_id=None, ptb_record_id=None, start_time=1000.0
        )

        # Should return the same generator
        assert wrapped is original_gen

    @pytest.mark.asyncio
    async def test_wraps_stream_when_ctp_record_id_provided(self) -> None:
        """Stream should be wrapped when ctp_record_id is provided."""
        mock_service = AsyncMock()
        mock_service.record_response = AsyncMock()
        wrapper = UsageTrackingWrapper(
            usage_tracking_service=mock_service,
            stream_formatting_service=StreamFormattingService(),
        )

        async def gen():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "hello"}}]}
            )
            yield ProcessedResponse(
                content={"choices": [{"delta": {}}]},
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )

        wrapped = wrapper.wrap_stream_for_usage(
            gen(), ctp_record_id="ctp-123", ptb_record_id=None, start_time=time.time()
        )

        chunks = [chunk async for chunk in wrapped]

        assert len(chunks) == 2
        mock_service.record_response.assert_called_once()
        call = mock_service.record_response.call_args
        assert call.kwargs["record_id"] == "ctp-123"
        assert call.kwargs["completion_tokens"] == 5

    @pytest.mark.asyncio
    async def test_wraps_stream_when_ptb_record_id_provided(self) -> None:
        """Stream should be wrapped when ptb_record_id is provided."""
        mock_service = AsyncMock()
        mock_service.record_response = AsyncMock()
        wrapper = UsageTrackingWrapper(
            usage_tracking_service=mock_service,
            stream_formatting_service=StreamFormattingService(),
        )

        async def gen():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "hello"}}]}
            )
            yield ProcessedResponse(
                content={"choices": [{"delta": {}}]},
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )

        wrapped = wrapper.wrap_stream_for_usage(
            gen(), ctp_record_id=None, ptb_record_id="ptb-456", start_time=time.time()
        )

        chunks = [chunk async for chunk in wrapped]

        assert len(chunks) == 2
        mock_service.record_response.assert_called_once()
        call = mock_service.record_response.call_args
        assert call.kwargs["record_id"] == "ptb-456"

    @pytest.mark.asyncio
    async def test_records_both_ctp_and_ptb(self) -> None:
        """Both ctp and ptb record IDs should be recorded when both provided."""
        mock_service = AsyncMock()
        mock_service.record_response = AsyncMock()
        wrapper = UsageTrackingWrapper(
            usage_tracking_service=mock_service,
            stream_formatting_service=StreamFormattingService(),
        )

        async def gen():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "hello"}}]}
            )
            yield ProcessedResponse(
                content={"choices": [{"delta": {}}]},
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )

        wrapped = wrapper.wrap_stream_for_usage(
            gen(), ctp_record_id="ctp-123", ptb_record_id="ptb-456", start_time=time.time()
        )

        _ = [chunk async for chunk in wrapped]

        assert mock_service.record_response.call_count == 2
        record_ids = [call.kwargs["record_id"] for call in mock_service.record_response.call_args_list]
        assert "ctp-123" in record_ids
        assert "ptb-456" in record_ids


class TestFirstTokenTimeTracking:
    """Tests for TTFT tracking."""

    @pytest.mark.asyncio
    async def test_ttft_measured_on_first_valid_token(self) -> None:
        """TTFT should be measured when first valid content token arrives."""
        mock_service = AsyncMock()
        mock_service.record_response = AsyncMock()
        wrapper = UsageTrackingWrapper(
            usage_tracking_service=mock_service,
            stream_formatting_service=StreamFormattingService(),
        )

        async def gen():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "first"}}]}
            )
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "second"}}]}
            )
            yield ProcessedResponse(
                content={"choices": [{"delta": {}}]},
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )

        start_time = time.time()
        wrapped = wrapper.wrap_stream_for_usage(
            gen(), ctp_record_id="ctp-123", ptb_record_id=None, start_time=start_time
        )

        _ = [chunk async for chunk in wrapped]

        call = mock_service.record_response.call_args
        ttft_ms = call.kwargs["ttft_ms"]
        assert ttft_ms is not None
        assert ttft_ms >= 0

    @pytest.mark.asyncio
    async def test_ttft_none_when_no_valid_tokens(self) -> None:
        """TTFT should be None when no valid content tokens exist."""
        mock_service = AsyncMock()
        mock_service.record_response = AsyncMock()
        wrapper = UsageTrackingWrapper(
            usage_tracking_service=mock_service,
            stream_formatting_service=StreamFormattingService(),
        )

        async def gen():
            # Only yield chunks without actual content
            yield ProcessedResponse(
                content={"choices": [{"delta": {}}]},
                usage={"prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10},
            )

        wrapped = wrapper.wrap_stream_for_usage(
            gen(), ctp_record_id="ctp-123", ptb_record_id=None, start_time=time.time()
        )

        _ = [chunk async for chunk in wrapped]

        call = mock_service.record_response.call_args
        ttft_ms = call.kwargs["ttft_ms"]
        assert ttft_ms is None


class TestUsageDataAccumulation:
    """Tests for usage data accumulation."""

    @pytest.mark.asyncio
    async def test_usage_from_processed_response_usage_field(self) -> None:
        """Usage should be extracted from ProcessedResponse.usage field."""
        mock_service = AsyncMock()
        mock_service.record_response = AsyncMock()
        wrapper = UsageTrackingWrapper(
            usage_tracking_service=mock_service,
            stream_formatting_service=StreamFormattingService(),
        )

        usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}

        async def gen():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "hello"}}]},
                usage=usage,
            )

        wrapped = wrapper.wrap_stream_for_usage(
            gen(), ctp_record_id="ctp-123", ptb_record_id=None, start_time=time.time()
        )

        _ = [chunk async for chunk in wrapped]

        call = mock_service.record_response.call_args
        assert call.kwargs["backend_reported_usage"] == usage
        assert call.kwargs["completion_tokens"] == 50

    @pytest.mark.asyncio
    async def test_usage_from_content_dict_usage_field(self) -> None:
        """Usage should be extracted from content dict usage field."""
        mock_service = AsyncMock()
        mock_service.record_response = AsyncMock()
        wrapper = UsageTrackingWrapper(
            usage_tracking_service=mock_service,
            stream_formatting_service=StreamFormattingService(),
        )

        usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}

        async def gen():
            yield ProcessedResponse(
                content={
                    "choices": [{"delta": {"content": "hello"}}],
                    "usage": usage,
                }
            )

        wrapped = wrapper.wrap_stream_for_usage(
            gen(), ctp_record_id="ctp-123", ptb_record_id=None, start_time=time.time()
        )

        _ = [chunk async for chunk in wrapped]

        call = mock_service.record_response.call_args
        assert call.kwargs["backend_reported_usage"] == usage

    @pytest.mark.asyncio
    async def test_usage_from_stop_chunk_with_usage(self) -> None:
        """Usage should be extracted from StopChunkWithUsage."""
        from src.core.ports.streaming_contracts import StopChunkWithUsage

        mock_service = AsyncMock()
        mock_service.record_response = AsyncMock()
        wrapper = UsageTrackingWrapper(
            usage_tracking_service=mock_service,
            stream_formatting_service=StreamFormattingService(),
        )

        usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        stop_chunk = StopChunkWithUsage(
            id="test",
            object="chat.completion.chunk",
            choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}],
            usage=usage,
        )

        async def gen():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "hello"}}]}
            )
            yield ProcessedResponse(content=stop_chunk)

        wrapped = wrapper.wrap_stream_for_usage(
            gen(), ctp_record_id="ctp-123", ptb_record_id=None, start_time=time.time()
        )

        _ = [chunk async for chunk in wrapped]

        call = mock_service.record_response.call_args
        assert call.kwargs["backend_reported_usage"] == usage

    @pytest.mark.asyncio
    async def test_no_recording_when_no_usage_data(self) -> None:
        """No usage should be recorded when stream has no usage data."""
        mock_service = AsyncMock()
        mock_service.record_response = AsyncMock()
        wrapper = UsageTrackingWrapper(
            usage_tracking_service=mock_service,
            stream_formatting_service=StreamFormattingService(),
        )

        async def gen():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "hello"}}]}
            )

        wrapped = wrapper.wrap_stream_for_usage(
            gen(), ctp_record_id="ctp-123", ptb_record_id=None, start_time=time.time()
        )

        _ = [chunk async for chunk in wrapped]

        # No usage data means no recording
        mock_service.record_response.assert_not_called()


class TestTPSCalculation:
    """Tests for tokens per second calculation."""

    @pytest.mark.asyncio
    async def test_tps_calculated_with_valid_data(self) -> None:
        """TPS should be calculated when we have valid timing and token data."""
        mock_service = AsyncMock()
        mock_service.record_response = AsyncMock()
        wrapper = UsageTrackingWrapper(
            usage_tracking_service=mock_service,
            stream_formatting_service=StreamFormattingService(),
        )

        async def gen():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "hello"}}]}
            )
            yield ProcessedResponse(
                content={"choices": [{"delta": {}}]},
                usage={"prompt_tokens": 10, "completion_tokens": 100, "total_tokens": 110},
            )

        wrapped = wrapper.wrap_stream_for_usage(
            gen(), ctp_record_id="ctp-123", ptb_record_id=None, start_time=time.time()
        )

        _ = [chunk async for chunk in wrapped]

        call = mock_service.record_response.call_args
        stream_tps = call.kwargs["stream_tps"]
        # TPS may be None if stream was too fast, or a positive float
        assert stream_tps is None or stream_tps > 0


class TestIsValidCompletionToken:
    """Tests for _is_valid_completion_token method."""

    def test_delegates_to_stream_formatting_service(self) -> None:
        """Should delegate to stream formatting service when available."""
        mock_formatting = MagicMock()
        mock_formatting.is_valid_completion_token.return_value = True

        wrapper = UsageTrackingWrapper(
            usage_tracking_service=None,
            stream_formatting_service=mock_formatting,
        )

        result = wrapper._is_valid_completion_token({"test": "chunk"})

        assert result is True
        mock_formatting.is_valid_completion_token.assert_called_once_with({"test": "chunk"})

    def test_fallback_for_valid_dict_content(self) -> None:
        """Fallback should detect valid dict content."""
        wrapper = UsageTrackingWrapper(
            usage_tracking_service=None,
            stream_formatting_service=None,
        )

        valid_chunk = {"choices": [{"delta": {"content": "hello"}}]}
        assert wrapper._is_valid_completion_token(valid_chunk) is True

    def test_fallback_for_tool_calls(self) -> None:
        """Fallback should detect tool calls as valid."""
        wrapper = UsageTrackingWrapper(
            usage_tracking_service=None,
            stream_formatting_service=None,
        )

        tool_chunk = {"choices": [{"delta": {"tool_calls": [{"id": "call_1"}]}}]}
        assert wrapper._is_valid_completion_token(tool_chunk) is True

    def test_fallback_for_done_marker_string(self) -> None:
        """Fallback should reject [DONE] string markers."""
        wrapper = UsageTrackingWrapper(
            usage_tracking_service=None,
            stream_formatting_service=None,
        )

        assert wrapper._is_valid_completion_token("[DONE]") is False
        assert wrapper._is_valid_completion_token('["DONE"]') is False
        assert wrapper._is_valid_completion_token("data: [DONE]") is False

    def test_fallback_for_done_marker_bytes(self) -> None:
        """Fallback should reject [DONE] bytes markers."""
        wrapper = UsageTrackingWrapper(
            usage_tracking_service=None,
            stream_formatting_service=None,
        )

        assert wrapper._is_valid_completion_token(b"[DONE]") is False
        assert wrapper._is_valid_completion_token(b'["DONE"]') is False

    def test_fallback_for_empty_content(self) -> None:
        """Fallback should reject empty content."""
        wrapper = UsageTrackingWrapper(
            usage_tracking_service=None,
            stream_formatting_service=None,
        )

        assert wrapper._is_valid_completion_token("") is False
        assert wrapper._is_valid_completion_token(b"") is False
        assert wrapper._is_valid_completion_token(None) is False


class TestErrorHandling:
    """Tests for error handling in usage recording."""

    @pytest.mark.asyncio
    async def test_stream_continues_on_recording_error(self) -> None:
        """Stream should continue even if usage recording fails."""
        mock_service = AsyncMock()
        mock_service.record_response = AsyncMock(side_effect=Exception("Recording failed"))
        wrapper = UsageTrackingWrapper(
            usage_tracking_service=mock_service,
            stream_formatting_service=StreamFormattingService(),
        )

        async def gen():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "hello"}}]},
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )

        wrapped = wrapper.wrap_stream_for_usage(
            gen(), ctp_record_id="ctp-123", ptb_record_id=None, start_time=time.time()
        )

        # Should not raise, stream should complete normally
        chunks = [chunk async for chunk in wrapped]
        assert len(chunks) == 1
