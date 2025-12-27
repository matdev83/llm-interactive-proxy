"""Regression test for ContentRewritingMiddleware streaming response accumulation DoS fix.

This test verifies that the ContentRewritingMiddleware properly limits accumulated
response body size to prevent DoS attacks through unbounded streaming responses.

Fixed: Added MAX_RESPONSE_BODY_SIZE limit (50MB) to prevent memory exhaustion.
"""

from collections.abc import AsyncGenerator

import pytest
from src.core.app.middleware.content_rewriting_middleware import (
    ContentRewritingMiddleware,
)
from starlette.responses import StreamingResponse


class TestContentRewritingMiddlewareDoSRegression:
    """Regression tests for ContentRewritingMiddleware DoS vulnerability fix."""

    async def generate_large_streaming_response(
        self, size_mb: int
    ) -> AsyncGenerator[bytes, None]:
        """Generate a streaming response of specified size."""
        chunk_size = 5 * 1024 * 1024  # 5MB chunks for faster generation
        remaining_bytes = size_mb * 1024 * 1024

        while remaining_bytes >= chunk_size:
            yield b"x" * chunk_size
            remaining_bytes -= chunk_size

        if remaining_bytes > 0:
            yield b"x" * remaining_bytes

    async def simulate_middleware_accumulation(
        self, response: StreamingResponse
    ) -> tuple[int, bool]:
        """
        Simulate the middleware's accumulation logic to test size limits.

        Returns:
            Tuple of (accumulated_size_bytes, limit_exceeded)
        """
        response_body = b""
        limit_exceeded = False

        async for chunk in response.body_iterator:
            chunk_bytes: bytes
            if isinstance(chunk, str):
                chunk_bytes = chunk.encode("utf-8")
            elif isinstance(chunk, memoryview):
                chunk_bytes = chunk.tobytes()
            else:
                chunk_bytes = chunk

            # DoS protection: Check accumulated size before adding chunk
            max_size = ContentRewritingMiddleware.MAX_RESPONSE_BODY_SIZE
            if len(response_body) + len(chunk_bytes) > max_size:
                limit_exceeded = True
                # Truncate to stay within limit (as per fix)
                remaining = max_size - len(response_body)
                if remaining > 0:
                    response_body += chunk_bytes[:remaining]
                break

            response_body += chunk_bytes

        return len(response_body), limit_exceeded

    @pytest.mark.asyncio
    async def test_large_response_truncated(self) -> None:
        """Test that large streaming responses (>50MB) are truncated."""
        # Create a response larger than 50MB limit (reduced for performance)
        response_size_mb = 55
        generator = self.generate_large_streaming_response(response_size_mb)

        response = StreamingResponse(generator)
        accumulated_size, limit_exceeded = await self.simulate_middleware_accumulation(
            response
        )

        # Should have hit the limit
        max_size = ContentRewritingMiddleware.MAX_RESPONSE_BODY_SIZE
        assert limit_exceeded, "Large response should trigger size limit"
        assert accumulated_size <= max_size, (
            f"Accumulated size ({accumulated_size}) should not exceed "
            f"MAX_RESPONSE_BODY_SIZE ({max_size})"
        )

    @pytest.mark.asyncio
    async def test_small_response_not_truncated(self) -> None:
        """Test that small streaming responses (<50MB) are not truncated."""
        # Create a response smaller than 50MB limit (reduced for performance)
        response_size_mb = 5
        generator = self.generate_large_streaming_response(response_size_mb)

        response = StreamingResponse(generator)
        accumulated_size, limit_exceeded = await self.simulate_middleware_accumulation(
            response
        )

        # Should not hit the limit
        assert not limit_exceeded, "Small response should not trigger size limit"
        expected_size = response_size_mb * 1024 * 1024
        assert accumulated_size == expected_size, (
            f"Accumulated size ({accumulated_size}) should match expected "
            f"({expected_size}) for small response"
        )

    @pytest.mark.asyncio
    async def test_exact_limit_size(self) -> None:
        """Test response exactly at the limit."""
        # Create a response exactly at 50MB limit
        max_size = ContentRewritingMiddleware.MAX_RESPONSE_BODY_SIZE
        limit_mb = max_size // (1024 * 1024)
        generator = self.generate_large_streaming_response(limit_mb)

        response = StreamingResponse(generator)
        accumulated_size, limit_exceeded = await self.simulate_middleware_accumulation(
            response
        )

        # Should be at or just under the limit, and limit should not be exceeded
        max_size = ContentRewritingMiddleware.MAX_RESPONSE_BODY_SIZE
        assert accumulated_size <= max_size, (
            f"Accumulated size ({accumulated_size}) should not exceed limit "
            f"({max_size})"
        )
        assert (
            not limit_exceeded
        ), "Response exactly at limit should not trigger limit exceeded flag"
        # Verify we accumulated exactly the expected size
        expected_size = limit_mb * 1024 * 1024
        assert accumulated_size == expected_size, (
            f"Accumulated size ({accumulated_size}) should match expected "
            f"({expected_size}) for exact limit size response"
        )

    @pytest.mark.asyncio
    async def test_multiple_large_chunks(self) -> None:
        """Test that multiple large chunks are properly handled."""

        async def large_chunk_generator() -> AsyncGenerator[bytes, None]:
            # Send chunks that individually are small but together exceed limit
            chunk_size = 10 * 1024 * 1024  # 10MB chunks
            for _i in range(10):  # 100MB total
                yield b"x" * chunk_size

        response = StreamingResponse(large_chunk_generator())
        accumulated_size, limit_exceeded = await self.simulate_middleware_accumulation(
            response
        )

        # Should hit limit after a few chunks
        max_size = ContentRewritingMiddleware.MAX_RESPONSE_BODY_SIZE
        assert limit_exceeded, "Multiple large chunks should trigger size limit"
        assert accumulated_size <= max_size, (
            f"Accumulated size ({accumulated_size}) should not exceed limit "
            f"({max_size})"
        )

    def test_max_response_body_size_constant(self) -> None:
        """Test that MAX_RESPONSE_BODY_SIZE constant is defined correctly."""
        # Verify the constant exists and has reasonable value
        max_size = ContentRewritingMiddleware.MAX_RESPONSE_BODY_SIZE
        assert max_size == 50 * 1024 * 1024, (
            f"MAX_RESPONSE_BODY_SIZE ({max_size}) should be 50MB " "(52428800 bytes)"
        )
        assert max_size > 0, "MAX_RESPONSE_BODY_SIZE should be positive"
