"""
Performance regression tests for streaming contract choices.

These tests verify that streaming contract conversions do not introduce
buffering that impacts time-to-first-byte or streaming throughput.

Requirement 5.4: While streaming responses are processed, the LLM Proxy
shall avoid buffering entire streams solely for contract conversion or mutation.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import pytest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.transport.fastapi.response_adapters import to_fastapi_streaming_response

from tests.unit.fixtures.markers import real_time


class TestStreamingNoBuffering:
    """Verify streaming contract conversions don't introduce buffering."""

    async def _create_test_stream(
        self, chunk_count: int, delay: float = 0.01
    ) -> AsyncIterator[StreamingContent]:
        """Create a test stream with known chunk count and timing."""
        for i in range(chunk_count):
            yield StreamingContent(
                content=f"chunk-{i}",
                metadata={"index": i},
                is_done=(i == chunk_count - 1),
            )
            await asyncio.sleep(delay)

    @pytest.mark.asyncio
    @real_time(reason="This test measures actual time-to-first-byte performance and requires real system time to validate streaming latency")
    async def test_streaming_yields_chunks_immediately(self):
        """
        Requirement 5.4: Chunks should be yielded immediately without buffering.

        This test verifies that chunks are processed and yielded one at a time,
        not buffered until the entire stream is consumed.
        """
        chunk_count = 10
        stream = self._create_test_stream(chunk_count, delay=0.01)

        # Wrap in StreamingResponseEnvelope
        envelope = StreamingResponseEnvelope(
            content=stream,  # type: ignore[arg-type]
            media_type="text/event-stream",
        )

        # Convert to FastAPI streaming response
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
        )

        fastapi_response = to_fastapi_streaming_response(envelope, context=context)

        # Consume stream and measure time-to-first-byte
        first_chunk_time = None
        chunk_times = []
        start_time = time.time()

        async for _chunk_bytes in fastapi_response.body_iterator:  # type: ignore[attr-defined]
            chunk_time = time.time() - start_time
            if first_chunk_time is None:
                first_chunk_time = chunk_time
            chunk_times.append(chunk_time)

            # Verify we're getting chunks incrementally
            if len(chunk_times) == 1:
                # First chunk should arrive quickly (< 100ms for this test)
                assert (
                    first_chunk_time < 0.1
                ), f"Time-to-first-byte too slow: {first_chunk_time}s"

        # Verify we got all chunks (may include done marker, so >= chunk_count)
        assert (
            len(chunk_times) >= chunk_count
        ), f"Expected at least {chunk_count} chunks, got {len(chunk_times)}"

        # Verify chunks arrived incrementally (not all at once)
        # Each chunk should arrive after the previous one
        for i in range(1, len(chunk_times)):
            assert (
                chunk_times[i] > chunk_times[i - 1]
            ), "Chunks arrived out of order or buffered"

    @pytest.mark.asyncio
    @real_time(reason="This test measures actual conversion performance and requires real system time to validate conversion latency")
    async def test_streaming_content_to_typed_chunk_no_buffering(self):
        """
        Requirement 5.4: StreamingContent.to_typed_chunk() should not require buffering.

        This test verifies that converting a single chunk to typed contract
        doesn't require waiting for additional chunks.
        """
        # Create a single chunk
        chunk = StreamingContent(
            content="test content",
            metadata={"test": "value"},
            is_done=False,
        )

        # Convert to typed chunk - should be immediate, no buffering
        start_time = time.time()
        typed_chunk = chunk.to_typed_chunk()
        conversion_time = time.time() - start_time

        # Conversion should be fast (< 10ms for a single chunk)
        assert (
            conversion_time < 0.01
        ), f"Typed chunk conversion too slow: {conversion_time}s"

        # Verify conversion worked
        assert typed_chunk.payload.kind == "text"
        assert typed_chunk.payload.text == "test content"

    @pytest.mark.asyncio
    @real_time(reason="This test measures actual streaming throughput and requires real system time to validate performance characteristics")
    async def test_streaming_throughput_not_degraded(self):
        """
        Requirement 5.4: Streaming throughput should not be degraded by contract conversions.

        This test verifies that processing chunks through the streaming pipeline
        doesn't introduce significant overhead that degrades throughput.
        """
        chunk_count = 100
        stream = self._create_test_stream(chunk_count, delay=0)

        envelope = StreamingResponseEnvelope(
            content=stream,  # type: ignore[arg-type]
            media_type="text/event-stream",
        )

        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
        )

        fastapi_response = to_fastapi_streaming_response(envelope, context=context)

        # Measure throughput
        start_time = time.time()
        chunk_count_received = 0

        async for _ in fastapi_response.body_iterator:  # type: ignore[attr-defined]
            chunk_count_received += 1

        total_time = time.time() - start_time
        throughput = chunk_count_received / total_time if total_time > 0 else 0

        # Verify we got all chunks (may include done marker, so >= chunk_count)
        assert chunk_count_received >= chunk_count

        # Throughput should be reasonable (> 10 chunks/second for this test)
        # This is a conservative threshold - actual throughput should be much higher
        assert throughput > 10, f"Throughput too low: {throughput} chunks/second"
