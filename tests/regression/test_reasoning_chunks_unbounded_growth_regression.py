"""Regression test for reasoning_chunks unbounded growth fix.

This test verifies that StreamBufferState.reasoning_chunks deque is properly
bounded to prevent unbounded memory growth in long-running streams.
"""

from src.core.services.streaming.stream_context_registry import (
    StreamingContextRegistry,
)


class TestReasoningChunksUnboundedGrowthRegression:
    """Regression tests for reasoning_chunks unbounded growth fix."""

    def test_reasoning_chunks_bounded_by_max_limit(self) -> None:
        """Test that reasoning_chunks deque doesn't exceed MAX_REASONING_CHUNKS limit."""
        from src.core.services.streaming.stream_context_registry import (
            _MAX_REASONING_CHUNKS,
        )

        registry = StreamingContextRegistry()
        stream_id = "test-stream-1"

        # Get state
        state = registry.get_content_state(stream_id)

        # Try to add more than the limit
        num_chunks = _MAX_REASONING_CHUNKS + 500

        for i in range(num_chunks):
            reasoning_text = f"Reasoning chunk {i}: " + "x" * 100  # 100 chars each
            state.append_reasoning_chunk(reasoning_text)

        # Deque length should not exceed max limit
        assert len(state.reasoning_chunks) <= _MAX_REASONING_CHUNKS, (
            f"Reasoning chunks count ({len(state.reasoning_chunks)}) exceeded max limit "
            f"({_MAX_REASONING_CHUNKS}). Eviction is not working."
        )

    def test_reasoning_chunks_evicts_oldest_when_limit_reached(self) -> None:
        """Test that oldest reasoning chunks are evicted when limit is reached."""
        from src.core.services.streaming.stream_context_registry import (
            _MAX_REASONING_CHUNKS,
        )

        registry = StreamingContextRegistry()
        stream_id = "test-stream-1"
        state = registry.get_content_state(stream_id)

        # Add chunks up to limit
        for i in range(_MAX_REASONING_CHUNKS):
            reasoning_text = f"Chunk {i}"
            state.append_reasoning_chunk(reasoning_text)

        assert len(state.reasoning_chunks) == _MAX_REASONING_CHUNKS

        # Store first chunk content to verify it gets evicted
        first_chunk = state.reasoning_chunks[0]

        # Add more chunks - should evict oldest
        for i in range(_MAX_REASONING_CHUNKS, _MAX_REASONING_CHUNKS + 10):
            reasoning_text = f"Chunk {i}"
            state.append_reasoning_chunk(reasoning_text)

        # Should still be at max limit
        assert (
            len(state.reasoning_chunks) <= _MAX_REASONING_CHUNKS
        ), "Reasoning chunks exceeded max limit after adding more chunks."

        # First chunk should be evicted
        assert (
            state.reasoning_chunks[0] != first_chunk
        ), "Oldest reasoning chunk was not evicted."

    def test_reasoning_chunks_handles_large_streams(self) -> None:
        """Test that reasoning_chunks handles very long streams without memory leak."""
        from src.core.services.streaming.stream_context_registry import (
            _MAX_REASONING_CHUNKS,
        )

        registry = StreamingContextRegistry()
        stream_id = "test-stream-long"
        state = registry.get_content_state(stream_id)

        # Simulate a very long stream (100k chunks)
        num_chunks = 100000

        for i in range(num_chunks):
            reasoning_text = f"Reasoning chunk {i}: " + "x" * 100
            state.append_reasoning_chunk(reasoning_text)

            # Verify bounded growth periodically
            if (i + 1) % 10000 == 0:
                assert len(state.reasoning_chunks) <= _MAX_REASONING_CHUNKS, (
                    f"Reasoning chunks grew unbounded at iteration {i + 1}. "
                    f"Count: {len(state.reasoning_chunks)}, max: {_MAX_REASONING_CHUNKS}"
                )

        # Final check
        assert len(state.reasoning_chunks) <= _MAX_REASONING_CHUNKS, (
            f"Final reasoning chunks count ({len(state.reasoning_chunks)}) "
            f"exceeded max limit ({_MAX_REASONING_CHUNKS}) after long stream."
        )

    def test_reasoning_chunks_uses_append_method(self) -> None:
        """Test that append_reasoning_chunk method enforces limits."""
        from src.core.services.streaming.stream_context_registry import (
            _MAX_REASONING_CHUNKS,
        )

        registry = StreamingContextRegistry()
        stream_id = "test-stream-append"
        state = registry.get_content_state(stream_id)

        # Verify append_reasoning_chunk method exists
        assert hasattr(state, "append_reasoning_chunk"), (
            "append_reasoning_chunk method is missing. "
            "Direct append would bypass size limits."
        )

        # Use the method to add chunks
        for i in range(_MAX_REASONING_CHUNKS + 100):
            state.append_reasoning_chunk(f"Chunk {i}")

        # Should be bounded
        assert (
            len(state.reasoning_chunks) <= _MAX_REASONING_CHUNKS
        ), "append_reasoning_chunk method is not enforcing size limits."
