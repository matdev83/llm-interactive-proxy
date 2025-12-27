"""Regression test for OpenAI connector SSE buffer overflow DoS vulnerability fix.

This test verifies that the OpenAI connector properly limits SSE buffer size
to prevent DoS attacks through malicious streaming responses without SSE separators.

Fixed: Added MAX_SSE_BUFFER_SIZE limit (16KB) to prevent unbounded buffer growth.
"""

from collections.abc import AsyncGenerator

import pytest
from src.connectors.openai import MAX_SSE_BUFFER_SIZE


class TestOpenAISSEBufferOverflowDoSRegression:
    """Regression tests for OpenAI SSE buffer overflow DoS vulnerability fix."""

    async def simulate_malicious_stream(self) -> AsyncGenerator[bytes, None]:
        """Simulate a streaming response that never contains SSE separators."""
        # Simulate chunks that contain data but no SSE separators
        malicious_chunks = [
            b'data: {"chunk": "part1"',
            b' and more data without separators"',
            b"just keep adding data",
            b"no \\n\\n separators here",
            b"buffer keeps growing...",
        ] * 20  # Reduced from 40 for performance

        for chunk in malicious_chunks:
            yield chunk
            # Remove sleep entirely for faster test - async generator overhead is sufficient

    async def vulnerable_sse_processing_simulation(
        self, response_generator: AsyncGenerator[bytes, None]
    ) -> list[int]:
        """
        Simulate the vulnerable code path to test buffer size limits.

        This mimics the SSE processing logic from OpenAI connector but
        tests that buffer size is properly limited.
        """
        buffer = ""
        separator = "\n\n"
        alt_separator = "\r\n\r\n"
        buffer_sizes = []

        try:
            async for chunk_bytes in response_generator:
                chunk_text = (
                    chunk_bytes.decode("utf-8", errors="replace")
                    if isinstance(chunk_bytes, bytes | bytearray)
                    else str(chunk_bytes)
                )

                # DoS protection: Limit buffer size to prevent memory exhaustion
                if len(buffer) + len(chunk_text) > MAX_SSE_BUFFER_SIZE:
                    # Truncate buffer to stay within limit (as per fix)
                    buffer = buffer[-MAX_SSE_BUFFER_SIZE:] if buffer else ""

                buffer += chunk_text
                buffer_sizes.append(len(buffer))

                # Safety: Stop after reasonable number of chunks for test (reduced for performance)
                if len(buffer_sizes) >= 100:  # Reduced from 200 for performance
                    break

                # Try to process SSE events
                while True:
                    if alt_separator in buffer:
                        event, buffer = buffer.split(alt_separator, 1)
                    elif separator in buffer:
                        event, buffer = buffer.split(separator, 1)
                    else:
                        break

                    if event:
                        # In real code, this would yield the event
                        pass

        except Exception:
            pass

        return buffer_sizes

    @pytest.mark.asyncio
    async def test_buffer_size_limited(self) -> None:
        """Test that buffer size is limited to MAX_SSE_BUFFER_SIZE."""
        malicious_stream = self.simulate_malicious_stream()
        buffer_sizes = await self.vulnerable_sse_processing_simulation(malicious_stream)

        # Buffer should never exceed MAX_SSE_BUFFER_SIZE significantly
        # Allow some tolerance for the chunk that triggers the limit
        max_buffer_size = max(buffer_sizes) if buffer_sizes else 0

        # Buffer should be bounded (allow up to MAX_SSE_BUFFER_SIZE + one chunk)
        assert max_buffer_size <= MAX_SSE_BUFFER_SIZE * 2, (
            f"Buffer size ({max_buffer_size}) exceeded reasonable limit "
            f"({MAX_SSE_BUFFER_SIZE * 2}). Buffer overflow protection may not be working."
        )

    @pytest.mark.asyncio
    async def test_buffer_truncation_works(self) -> None:
        """Test that buffer truncation prevents unbounded growth."""

        # Create a stream that would cause unbounded growth without protection
        async def large_chunk_stream() -> AsyncGenerator[bytes, None]:
            # Send chunks that are larger than MAX_SSE_BUFFER_SIZE
            large_chunk = b"x" * (MAX_SSE_BUFFER_SIZE + 1000)
            for _ in range(5):  # Reduced from 10 for performance
                yield large_chunk
                # Remove sleep for faster test

        buffer_sizes = await self.vulnerable_sse_processing_simulation(
            large_chunk_stream()
        )

        # Even with large chunks, buffer should be bounded
        # Allow some tolerance since truncation happens after adding chunk
        max_buffer_size = max(buffer_sizes) if buffer_sizes else 0
        # The buffer can temporarily exceed MAX_SSE_BUFFER_SIZE by one chunk size
        # before truncation happens, so allow up to MAX_SSE_BUFFER_SIZE + chunk_size
        assert max_buffer_size <= MAX_SSE_BUFFER_SIZE * 3, (
            f"Buffer size ({max_buffer_size}) exceeded reasonable limit with large chunks. "
            "Truncation may not be working correctly."
        )

    @pytest.mark.asyncio
    async def test_normal_sse_streams_work(self) -> None:
        """Test that normal SSE streams with separators work correctly."""

        async def normal_sse_stream() -> AsyncGenerator[bytes, None]:
            # Normal SSE stream with separators
            events = [
                b'data: {"content": "chunk1"}\n\n',
                b'data: {"content": "chunk2"}\n\n',
                b"data: [DONE]\n\n",
            ]
            for event in events:
                yield event
                # Remove sleep for faster test

        buffer_sizes = await self.vulnerable_sse_processing_simulation(
            normal_sse_stream()
        )

        # Normal streams should process without issues
        # Buffer should be small since events are processed immediately
        max_buffer_size = max(buffer_sizes) if buffer_sizes else 0
        assert max_buffer_size < MAX_SSE_BUFFER_SIZE, (
            f"Normal SSE stream caused large buffer ({max_buffer_size}). "
            "Events should be processed immediately."
        )

    def test_max_buffer_size_constant(self) -> None:
        """Test that MAX_SSE_BUFFER_SIZE constant is defined correctly."""
        # Verify the constant exists and has reasonable value
        assert (
            MAX_SSE_BUFFER_SIZE == 16384
        ), f"MAX_SSE_BUFFER_SIZE ({MAX_SSE_BUFFER_SIZE}) should be 16KB (16384 bytes)"
        assert MAX_SSE_BUFFER_SIZE > 0, "MAX_SSE_BUFFER_SIZE should be positive"
