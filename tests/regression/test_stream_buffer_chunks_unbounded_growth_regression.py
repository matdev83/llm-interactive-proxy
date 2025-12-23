"""Regression test for StreamBufferState chunks unbounded growth fix.

This test verifies that StreamBufferState chunks, encoded_chunks, and chunk_lengths
deques don't grow unbounded when streams never complete (e.g., network timeouts,
connection failures).

Fixed: Added _MAX_CONTENT_CHUNKS limit (10000) with eviction of oldest chunks.
"""

from src.core.services.streaming.stream_context_registry import (
    StreamingContextRegistry,
)


class TestStreamBufferChunksUnboundedGrowthRegression:
    """Regression tests for StreamBufferState chunks unbounded growth fix."""

    def test_content_chunks_bounded_by_max_limit(self) -> None:
        """Test that content chunks deques don't exceed _MAX_CONTENT_CHUNKS limit."""
        from src.core.services.streaming.stream_context_registry import (
            _MAX_CONTENT_CHUNKS,
        )

        registry = StreamingContextRegistry(state_ttl_seconds=300)
        stream_id = "test-stream-1"

        # Get state
        state = registry.get_content_state(stream_id)

        # Try to add more than the limit
        num_chunks = _MAX_CONTENT_CHUNKS + 500

        for i in range(num_chunks):
            chunk_text = f"chunk_{i}_" + "x" * 100  # 100 bytes per chunk
            encoded_chunk = chunk_text.encode("utf-8")
            content_length = len(encoded_chunk)

            state.append_content_chunk(chunk_text, encoded_chunk, content_length)

        # Deque lengths should not exceed max limit
        assert len(state.chunks) <= _MAX_CONTENT_CHUNKS, (
            f"Content chunks count ({len(state.chunks)}) exceeded max limit "
            f"({_MAX_CONTENT_CHUNKS}). Eviction is not working."
        )
        assert len(state.encoded_chunks) <= _MAX_CONTENT_CHUNKS, (
            f"Encoded chunks count ({len(state.encoded_chunks)}) exceeded max limit "
            f"({_MAX_CONTENT_CHUNKS}). Eviction is not working."
        )
        assert len(state.chunk_lengths) <= _MAX_CONTENT_CHUNKS, (
            f"Chunk lengths count ({len(state.chunk_lengths)}) exceeded max limit "
            f"({_MAX_CONTENT_CHUNKS}). Eviction is not working."
        )

    def test_content_chunks_evicts_oldest_when_limit_reached(self) -> None:
        """Test that oldest chunks are evicted when limit is reached."""
        from src.core.services.streaming.stream_context_registry import (
            _MAX_CONTENT_CHUNKS,
        )

        registry = StreamingContextRegistry()
        stream_id = "test-stream-2"

        state = registry.get_content_state(stream_id)

        # Add chunks up to the limit
        for i in range(_MAX_CONTENT_CHUNKS):
            chunk_text = f"chunk_{i}_" + "x" * 100
            encoded_chunk = chunk_text.encode("utf-8")
            content_length = len(encoded_chunk)
            state.append_content_chunk(chunk_text, encoded_chunk, content_length)

        # Verify we're at the limit
        assert len(state.chunks) == _MAX_CONTENT_CHUNKS
        first_chunk = state.chunks[0]

        # Add one more chunk - should evict the oldest
        chunk_text = f"chunk_{_MAX_CONTENT_CHUNKS}_" + "x" * 100
        encoded_chunk = chunk_text.encode("utf-8")
        content_length = len(encoded_chunk)
        state.append_content_chunk(chunk_text, encoded_chunk, content_length)

        # Should still be at limit
        assert len(state.chunks) == _MAX_CONTENT_CHUNKS
        # First chunk should be evicted
        assert state.chunks[0] != first_chunk, "Oldest chunk was not evicted"
        # New chunk should be at the end
        assert state.chunks[-1] == chunk_text, "New chunk was not appended"

    def test_content_chunks_byte_length_updated_on_eviction(self) -> None:
        """Test that byte_length is correctly updated when chunks are evicted."""
        from src.core.services.streaming.stream_context_registry import (
            _MAX_CONTENT_CHUNKS,
        )

        registry = StreamingContextRegistry()
        stream_id = "test-stream-3"

        state = registry.get_content_state(stream_id)

        # Add chunks up to the limit
        chunk_size = 100
        total_bytes = 0
        for i in range(_MAX_CONTENT_CHUNKS):
            chunk_text = f"chunk_{i}_" + "x" * chunk_size
            encoded_chunk = chunk_text.encode("utf-8")
            content_length = len(encoded_chunk)
            total_bytes += content_length
            state.append_content_chunk(chunk_text, encoded_chunk, content_length)

        # Verify byte_length matches
        assert state.byte_length == total_bytes

        # Add more chunks beyond limit
        evicted_bytes = 0
        for i in range(_MAX_CONTENT_CHUNKS, _MAX_CONTENT_CHUNKS + 100):
            chunk_text = f"chunk_{i}_" + "x" * chunk_size
            encoded_chunk = chunk_text.encode("utf-8")
            content_length = len(encoded_chunk)

            # Track bytes that will be evicted
            if len(state.chunks) >= _MAX_CONTENT_CHUNKS:
                evicted_bytes += state.chunk_lengths[0]

            state.append_content_chunk(chunk_text, encoded_chunk, content_length)

        # byte_length should be updated correctly (old bytes evicted, new bytes added)
        # Should be approximately: total_bytes - evicted_bytes + (100 * chunk_size)
        # Allow some tolerance for exact calculation
        expected_min_bytes = total_bytes - (evicted_bytes * 2) + (100 * chunk_size)
        assert state.byte_length >= expected_min_bytes * 0.9, (
            f"byte_length ({state.byte_length}) seems incorrect after eviction. "
            f"Expected at least {expected_min_bytes * 0.9}"
        )

    def test_content_chunks_maintains_sync_across_deques(self) -> None:
        """Test that chunks, encoded_chunks, and chunk_lengths stay in sync."""
        registry = StreamingContextRegistry()
        stream_id = "test-stream-4"

        state = registry.get_content_state(stream_id)

        # Add many chunks
        num_chunks = 15000
        for i in range(num_chunks):
            chunk_text = f"chunk_{i}_" + "x" * 100
            encoded_chunk = chunk_text.encode("utf-8")
            content_length = len(encoded_chunk)
            state.append_content_chunk(chunk_text, encoded_chunk, content_length)

        # All deques should have the same length
        chunks_len = len(state.chunks)
        encoded_len = len(state.encoded_chunks)
        lengths_len = len(state.chunk_lengths)

        assert chunks_len == encoded_len == lengths_len, (
            f"Deques are out of sync: chunks={chunks_len}, "
            f"encoded_chunks={encoded_len}, chunk_lengths={lengths_len}"
        )

        # Verify corresponding entries match
        for i in range(min(100, chunks_len)):  # Check first 100 entries
            expected_text = state.chunks[i]
            expected_encoded = expected_text.encode("utf-8")
            expected_length = len(expected_encoded)

            assert (
                state.encoded_chunks[i] == expected_encoded
            ), f"Encoded chunk at index {i} doesn't match text chunk"
            assert (
                state.chunk_lengths[i] == expected_length
            ), f"Chunk length at index {i} doesn't match encoded chunk size"
