"""Regression test for StreamingContextRegistry max limit enforcement fix.

This test verifies that StreamingContextRegistry properly enforces the
_MAX_STREAM_STATES limit to prevent unbounded memory growth even when
streams are never accessed again.
"""

from src.core.services.streaming.stream_context_registry import StreamingContextRegistry


class TestStreamContextRegistryMaxLimitRegression:
    """Regression tests for StreamingContextRegistry max limit enforcement fix."""

    def test_max_limit_enforced_when_exceeding_limit(self) -> None:
        """Test that max limit prevents unbounded growth when creating many streams."""
        # Use smaller limit for test performance - still tests the same eviction logic
        test_max_limit = 1000
        num_streams = test_max_limit + 100

        # Create registry with test limit by monkeypatching the constant
        # This tests the same eviction logic without needing 10,000+ iterations
        original_max = StreamingContextRegistry._MAX_STREAM_STATES
        StreamingContextRegistry._MAX_STREAM_STATES = test_max_limit  # type: ignore[assignment]

        try:
            registry = StreamingContextRegistry(state_ttl_seconds=300)

            # Create more streams than the limit
            for i in range(num_streams):
                stream_id = f"stream_{i}"
                registry.get_content_state(stream_id)

                # States size should never exceed max limit
                states_size = len(registry._states)
                assert states_size <= test_max_limit, (
                    f"States size ({states_size}) exceeded max limit ({test_max_limit}) "
                    f"after creating {i+1} streams. Max limit enforcement is not working."
                )

            # Final size should be at or below max limit
            final_size = len(registry._states)
            assert final_size <= test_max_limit, (
                f"Final states size ({final_size}) exceeds max limit ({test_max_limit}). "
                "Max limit enforcement failed."
            )
        finally:
            StreamingContextRegistry._MAX_STREAM_STATES = original_max  # type: ignore[assignment]

    def test_max_limit_enforced_with_orphaned_streams(self) -> None:
        """Test that max limit is enforced even when streams are never accessed again."""
        # Use smaller limit for test performance - still tests the same eviction logic
        test_max_limit = 1000
        num_streams = test_max_limit + 100

        # Create registry with test limit by monkeypatching the constant
        # This tests the same eviction logic without needing 10,000+ iterations
        original_max = StreamingContextRegistry._MAX_STREAM_STATES
        StreamingContextRegistry._MAX_STREAM_STATES = test_max_limit  # type: ignore[assignment]

        try:
            registry = StreamingContextRegistry(state_ttl_seconds=300)

            # Create many streams that will never be accessed again
            # Check periodically instead of every iteration to reduce overhead
            check_interval = max(1, num_streams // 10)  # Check ~10 times
            for i in range(num_streams):
                stream_id = f"orphan_stream_{i}"
                registry.get_content_state(stream_id)

                # States size should never exceed max limit (check periodically for performance)
                if i % check_interval == 0 or i == num_streams - 1:
                    states_size = len(registry._states)
                    assert states_size <= test_max_limit, (
                        f"States size ({states_size}) exceeded max limit ({test_max_limit}) "
                        f"after creating orphaned stream {i+1}. Max limit enforcement failed."
                    )

            # Final size should be at or below max limit
            final_size = len(registry._states)
            assert final_size <= test_max_limit, (
                f"Final states size ({final_size}) exceeds max limit ({test_max_limit}) "
                "for orphaned streams. Max limit enforcement failed."
            )
        finally:
            StreamingContextRegistry._MAX_STREAM_STATES = original_max  # type: ignore[assignment]

    def test_max_limit_constant_value(self) -> None:
        """Test that _MAX_STREAM_STATES constant has expected value."""
        registry = StreamingContextRegistry()
        max_limit = registry._MAX_STREAM_STATES

        # Verify constant is defined and has reasonable value
        assert max_limit == 10000, (
            f"_MAX_STREAM_STATES ({max_limit}) should be 10000. "
            "Constant value may have changed."
        )
        assert max_limit > 0, "_MAX_STREAM_STATES should be positive"
