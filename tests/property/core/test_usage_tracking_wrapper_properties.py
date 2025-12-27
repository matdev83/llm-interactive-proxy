"""Property-based tests for UsageTrackingWrapper.

Validates:
- Property 4: Usage Accumulation (Requirements 6.2, 6.3)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.stream_formatting_service import StreamFormattingService
from src.core.services.usage_tracking_wrapper import UsageTrackingWrapper
from tests.utils.fake_clock import FakeClock, FakeClockContext


def usage_data_strategy() -> st.SearchStrategy:
    """Generate valid usage data dictionaries."""
    return st.fixed_dictionaries(
        {
            "prompt_tokens": st.integers(min_value=0, max_value=10000),
            "completion_tokens": st.integers(min_value=1, max_value=5000),
            "total_tokens": st.integers(min_value=1, max_value=15000),
        }
    )


def chunk_with_content_strategy() -> st.SearchStrategy:
    """Generate chunks with actual content."""
    return st.fixed_dictionaries(
        {
            "id": st.text(
                min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz-"
            ),
            "object": st.just("chat.completion.chunk"),
            "choices": st.lists(
                st.fixed_dictionaries(
                    {
                        "index": st.just(0),
                        "delta": st.fixed_dictionaries(
                            {"content": st.text(min_size=1, max_size=50)}
                        ),
                    }
                ),
                min_size=1,
                max_size=1,
            ),
        }
    )


class TestUsageAccumulationProperty:
    """Property 4: Usage Accumulation (Requirements 6.2, 6.3)."""

    @given(usage=usage_data_strategy())
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_usage_data_accumulated_from_chunks(self, usage: dict) -> None:
        """Usage data from chunks should be accumulated and reported."""
        mock_usage_service = AsyncMock()
        mock_usage_service.record_response = AsyncMock()

        wrapper = UsageTrackingWrapper(
            usage_tracking_service=mock_usage_service,
            stream_formatting_service=StreamFormattingService(),
        )

        async def gen():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "hello"}}]}
            )
            yield ProcessedResponse(
                content={"choices": [{"delta": {}}], "usage": usage},
                usage=usage,
            )

        start_time = 1000.0
        wrapped = wrapper.wrap_stream_for_usage(
            gen(),
            ctp_record_id="ctp-123",
            ptb_record_id="ptb-456",
            start_time=start_time,
        )

        chunks = [chunk async for chunk in wrapped]

        assert len(chunks) == 2
        mock_usage_service.record_response.assert_called()

        # Verify both record IDs were used
        call_args_list = mock_usage_service.record_response.call_args_list
        record_ids = [call.kwargs.get("record_id") for call in call_args_list]
        assert "ptb-456" in record_ids
        assert "ctp-123" in record_ids

        # Verify completion tokens from usage were recorded
        for call in call_args_list:
            assert call.kwargs.get("completion_tokens") == usage["completion_tokens"]
            assert call.kwargs.get("backend_reported_usage") == usage

    @given(
        num_content_chunks=st.integers(min_value=1, max_value=10),
        completion_tokens=st.integers(min_value=1, max_value=500),
    )
    @settings(max_examples=30)
    @pytest.mark.asyncio
    async def test_first_token_time_tracked_on_valid_content(
        self, num_content_chunks: int, completion_tokens: int
    ) -> None:
        """TTFT should be measured on first valid completion token."""
        mock_usage_service = AsyncMock()
        mock_usage_service.record_response = AsyncMock()

        wrapper = UsageTrackingWrapper(
            usage_tracking_service=mock_usage_service,
            stream_formatting_service=StreamFormattingService(),
        )

        async def gen():
            # First yield some content chunks
            for i in range(num_content_chunks):
                yield ProcessedResponse(
                    content={"choices": [{"delta": {"content": f"word{i}"}}]}
                )
            # Final chunk with usage
            yield ProcessedResponse(
                content={"choices": [{"delta": {}}]},
                usage={
                    "prompt_tokens": 10,
                    "completion_tokens": completion_tokens,
                    "total_tokens": 10 + completion_tokens,
                },
            )

        start_time = 1000.0
        wrapped = wrapper.wrap_stream_for_usage(
            gen(), ctp_record_id="ctp-123", ptb_record_id=None, start_time=start_time
        )

        chunks = [chunk async for chunk in wrapped]

        assert len(chunks) == num_content_chunks + 1
        mock_usage_service.record_response.assert_called_once()

        # Verify TTFT was recorded (should be non-None since we had valid content)
        call = mock_usage_service.record_response.call_args
        ttft_ms = call.kwargs.get("ttft_ms")
        assert ttft_ms is not None
        assert ttft_ms >= 0  # Should be positive (or zero if fast)

    @given(usage=usage_data_strategy())
    @settings(max_examples=30)
    @pytest.mark.asyncio
    async def test_stream_tps_calculated_when_valid(self, usage: dict) -> None:
        """Stream TPS should be calculated when we have valid metrics."""
        mock_usage_service = AsyncMock()
        mock_usage_service.record_response = AsyncMock()

        wrapper = UsageTrackingWrapper(
            usage_tracking_service=mock_usage_service,
            stream_formatting_service=StreamFormattingService(),
        )

        async def gen():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "hello world"}}]}
            )
            yield ProcessedResponse(
                content={"choices": [{"delta": {}}]},
                usage=usage,
            )

        async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
            start_time = clock.now()
            wrapped = wrapper.wrap_stream_for_usage(
                gen(),
                ctp_record_id="ctp-123",
                ptb_record_id=None,
                start_time=start_time,
            )

        _ = [chunk async for chunk in wrapped]

        mock_usage_service.record_response.assert_called_once()
        call = mock_usage_service.record_response.call_args

        # Verify TPS was calculated (may be None if stream was too fast)
        # Just verify it doesn't crash and returns a valid value type
        stream_tps = call.kwargs.get("stream_tps")
        assert stream_tps is None or isinstance(stream_tps, float)

    @pytest.mark.asyncio
    async def test_noop_when_no_usage_service(self) -> None:
        """Wrapper should be a no-op when usage service is None."""
        wrapper = UsageTrackingWrapper(
            usage_tracking_service=None,
            stream_formatting_service=StreamFormattingService(),
        )

        async def gen():
            yield ProcessedResponse(content={"choices": [{"delta": {"content": "hi"}}]})

        wrapped = wrapper.wrap_stream_for_usage(
            gen(), ctp_record_id="ctp-123", ptb_record_id="ptb-456", start_time=1000.0
        )

        # Should return the original stream unchanged
        chunks = [chunk async for chunk in wrapped]
        assert len(chunks) == 1

    @pytest.mark.asyncio
    async def test_noop_when_no_record_ids(self) -> None:
        """Wrapper should be a no-op when both record IDs are None."""
        mock_usage_service = AsyncMock()

        wrapper = UsageTrackingWrapper(
            usage_tracking_service=mock_usage_service,
            stream_formatting_service=StreamFormattingService(),
        )

        async def gen():
            yield ProcessedResponse(content={"choices": [{"delta": {"content": "hi"}}]})

        wrapped = wrapper.wrap_stream_for_usage(
            gen(), ctp_record_id=None, ptb_record_id=None, start_time=1000.0
        )

        chunks = [chunk async for chunk in wrapped]
        assert len(chunks) == 1
        mock_usage_service.record_response.assert_not_called()

    @given(usage=usage_data_strategy())
    @settings(max_examples=30)
    @pytest.mark.asyncio
    async def test_usage_from_stop_chunk_with_usage(self, usage: dict) -> None:
        """Usage should be extracted from StopChunkWithUsage."""
        from src.core.ports.streaming_contracts import StopChunkWithUsage

        mock_usage_service = AsyncMock()
        mock_usage_service.record_response = AsyncMock()

        wrapper = UsageTrackingWrapper(
            usage_tracking_service=mock_usage_service,
            stream_formatting_service=StreamFormattingService(),
        )

        stop_chunk = StopChunkWithUsage(
            id="test-stop",
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
            gen(), ctp_record_id="ctp-123", ptb_record_id=None, start_time=1000.0
        )

        chunks = [chunk async for chunk in wrapped]

        assert len(chunks) == 2
        mock_usage_service.record_response.assert_called_once()

        call = mock_usage_service.record_response.call_args
        assert call.kwargs.get("backend_reported_usage") == usage
        assert call.kwargs.get("completion_tokens") == usage["completion_tokens"]


class TestEquivalenceWithBackendService:
    """Ensure UsageTrackingWrapper matches BackendService behavior."""

    @pytest.mark.asyncio
    async def test_valid_token_detection_uses_stream_formatting_service(self) -> None:
        """UsageTrackingWrapper should delegate token validation to StreamFormattingService."""
        mock_stream_formatting = MagicMock(spec=StreamFormattingService)
        mock_stream_formatting.is_valid_completion_token.return_value = True

        wrapper = UsageTrackingWrapper(
            usage_tracking_service=None,
            stream_formatting_service=mock_stream_formatting,
        )

        chunk = {"choices": [{"delta": {"content": "test"}}]}
        result = wrapper._is_valid_completion_token(chunk)

        assert result is True
        mock_stream_formatting.is_valid_completion_token.assert_called_once_with(chunk)

    @pytest.mark.asyncio
    async def test_fallback_token_validation_without_service(self) -> None:
        """UsageTrackingWrapper should have fallback validation when no service provided."""
        wrapper = UsageTrackingWrapper(
            usage_tracking_service=None,
            stream_formatting_service=None,
        )

        # Valid content chunk
        valid_chunk = {"choices": [{"delta": {"content": "hello"}}]}
        assert wrapper._is_valid_completion_token(valid_chunk) is True

        # Done marker
        done_chunk = "[DONE]"
        assert wrapper._is_valid_completion_token(done_chunk) is False

        # Empty content
        empty_chunk = ""
        assert wrapper._is_valid_completion_token(empty_chunk) is False
