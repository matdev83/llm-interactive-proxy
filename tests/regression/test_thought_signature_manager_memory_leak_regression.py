"""Regression test for ThoughtSignatureManager secondary index memory leak fix.

This test verifies that the _by_tool_call secondary index doesn't accumulate
stale entries when the same tool_call_id is used across different sessions
and cache eviction occurs.
"""


from src.connectors.gemini_base.thought_signature_manager import ThoughtSignatureManager


class TestThoughtSignatureManagerMemoryLeakRegression:
    """Regression tests for ThoughtSignatureManager secondary index memory leak fix."""

    def test_secondary_index_stays_synchronized_with_cache(self) -> None:
        """Test that _by_tool_call doesn't accumulate orphaned entries."""
        manager = ThoughtSignatureManager(max_cache_size=5, ttl_seconds=10)

        # Simulate storing signatures with same tool_call_id across different sessions
        # This is the scenario that caused the memory leak
        for i in range(10):
            tc_id = f"tool_call_{i}"
            sig = f"signature_{i}"

            # Store with multiple sessions (same tc_id, different sessions)
            for session_id in ["session1", "session2"]:
                # Use the public API method to store signatures
                tool_call = {
                    "id": tc_id,
                    "extra_content": {"google": {"thought_signature": sig}},
                }
                manager.store_signatures_from_tool_calls(
                    [tool_call], session_id=session_id
                )

        # After eviction, secondary index should only contain entries that exist in cache
        final_cache_size = len(manager._cache)
        final_secondary_size = len(manager._by_tool_call)

        # Count orphaned entries (entries in secondary index not referenced in cache)
        orphaned_count = 0
        for tc_id in manager._by_tool_call:
            # Check if this tc_id is referenced in any cache key
            referenced = any(
                key.endswith(f":{tc_id}") or key == tc_id for key in manager._cache
            )
            if not referenced:
                orphaned_count += 1

        assert orphaned_count == 0, (
            f"Found {orphaned_count} orphaned entries in secondary index. "
            "Secondary index should stay synchronized with primary cache."
        )

        # Secondary index size should not exceed cache size significantly
        # (it can be equal or slightly less due to multiple sessions sharing same tc_id)
        assert final_secondary_size <= final_cache_size, (
            f"Secondary index size ({final_secondary_size}) exceeds cache size "
            f"({final_cache_size}). Secondary index should not accumulate stale entries."
        )

    def test_secondary_index_rebuilt_on_eviction(self) -> None:
        """Test that secondary index is properly rebuilt when cache entries are evicted."""
        manager = ThoughtSignatureManager(max_cache_size=3, ttl_seconds=10)

        # Add entries that will trigger eviction
        for i in range(5):
            tc_id = f"tc_{i}"
            sig = f"sig_{i}"
            tool_call = {
                "id": tc_id,
                "extra_content": {"google": {"thought_signature": sig}},
            }
            manager.store_signatures_from_tool_calls(
                [tool_call], session_id=f"session_{i}"
            )

        # Cache should be at max size
        assert len(manager._cache) <= manager._max_cache_size

        # All entries in secondary index should be referenced in cache
        for tc_id in manager._by_tool_call:
            referenced = any(
                key.endswith(f":{tc_id}") or key == tc_id for key in manager._cache
            )
            assert referenced, (
                f"Tool call ID {tc_id} in secondary index is not referenced in cache. "
                "Secondary index was not properly rebuilt after eviction."
            )

    def test_multiple_sessions_same_tool_call_id(self) -> None:
        """Test that same tool_call_id across sessions doesn't cause memory leak."""
        manager = ThoughtSignatureManager(max_cache_size=5, ttl_seconds=10)

        # Use same tool_call_id across multiple sessions
        tc_id = "shared_tool_call"
        for session_num in range(10):
            session_id = f"session_{session_num}"
            sig = f"signature_{session_num}"
            tool_call = {
                "id": tc_id,
                "extra_content": {"google": {"thought_signature": sig}},
            }
            manager.store_signatures_from_tool_calls([tool_call], session_id=session_id)

        # After eviction, secondary index should only have one entry for this tc_id
        # (the most recent one from cache)
        if tc_id in manager._by_tool_call:
            # The signature should match one of the entries still in cache
            cached_sig = manager._by_tool_call[tc_id]
            found_in_cache = any(
                sig == cached_sig
                for key, (sig, _) in manager._cache.items()
                if key.endswith(f":{tc_id}") or key == tc_id
            )
            assert found_in_cache, (
                f"Signature {cached_sig} in secondary index doesn't match any cache entry. "
                "Secondary index contains stale data."
            )
