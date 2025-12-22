"""Regression test for ThoughtSignatureManager anonymous entries memory leak fix.

This test verifies that ThoughtSignatureManager properly cleans up anonymous
entries (entries with session_id=None) to prevent unbounded memory growth.

Fixed: ThoughtSignatureManager.clear_all_anonymous() method was added to
clean up anonymous entries that were never cleaned up before.
"""

import time

import pytest

from src.connectors.gemini_base.thought_signature_manager import ThoughtSignatureManager


class TestThoughtSignatureAnonymousEntriesLeakRegression:
    """Regression tests for ThoughtSignatureManager anonymous entries leak fix."""

    @pytest.fixture
    def manager(self) -> ThoughtSignatureManager:
        """Create ThoughtSignatureManager for testing."""
        return ThoughtSignatureManager(max_cache_size=1000, ttl_seconds=3600)

    def test_anonymous_entries_accumulate_without_cleanup(
        self, manager: ThoughtSignatureManager
    ) -> None:
        """Test that anonymous entries accumulate without cleanup."""
        # Add many anonymous entries (session_id=None)
        for batch in range(10):
            anon_tool_calls = []
            for i in range(100):
                anon_tool_calls.append(
                    {
                        "id": f"anon_tool_{batch}_{i}",
                        "extra_content": {
                            "google": {
                                "thought_signature": f"anon_sig_{batch}_{i}_{time.time()}"
                            }
                        },
                    }
                )

            manager.store_signatures_from_tool_calls(anon_tool_calls, None)

        # Verify entries accumulated
        cache_size = len(manager._cache)
        secondary_size = len(manager._by_tool_call)

        assert cache_size > 0, "Anonymous entries should be stored"
        assert secondary_size > 0, "Secondary index should have entries"

    def test_clear_all_anonymous_removes_anonymous_entries(
        self, manager: ThoughtSignatureManager
    ) -> None:
        """Test that clear_all_anonymous() removes anonymous entries."""
        # Add anonymous entries
        anon_tool_calls = []
        for i in range(100):
            anon_tool_calls.append(
                {
                    "id": f"anon_tool_{i}",
                    "extra_content": {
                        "google": {"thought_signature": f"anon_sig_{i}"}
                    },
                }
            )

        manager.store_signatures_from_tool_calls(anon_tool_calls, None)

        initial_cache_size = len(manager._cache)
        initial_secondary_size = len(manager._by_tool_call)

        # Clear anonymous entries
        cleared = manager.clear_all_anonymous()

        final_cache_size = len(manager._cache)
        final_secondary_size = len(manager._by_tool_call)

        assert cleared > 0, "Should have cleared anonymous entries"
        assert final_cache_size < initial_cache_size, (
            "Cache size should decrease after clearing anonymous entries"
        )
        assert final_cache_size == 0, "All anonymous entries should be removed"
        assert final_secondary_size < initial_secondary_size, (
            "Secondary index should decrease after clearing anonymous entries"
        )

    def test_clear_all_anonymous_preserves_session_entries(
        self, manager: ThoughtSignatureManager
    ) -> None:
        """Test that clear_all_anonymous() preserves session-specific entries."""
        # Add session-specific entries
        session_tool_calls = []
        for i in range(50):
            session_tool_calls.append(
                {
                    "id": f"session_tool_{i}",
                    "extra_content": {
                        "google": {"thought_signature": f"session_sig_{i}"}
                    },
                }
            )

        manager.store_signatures_from_tool_calls(session_tool_calls, "test_session")

        # Add anonymous entries
        anon_tool_calls = []
        for i in range(50):
            anon_tool_calls.append(
                {
                    "id": f"anon_tool_{i}",
                    "extra_content": {
                        "google": {"thought_signature": f"anon_sig_{i}"}
                    },
                }
            )

        manager.store_signatures_from_tool_calls(anon_tool_calls, None)

        session_cache_before = len(
            [k for k in manager._cache if k.startswith("test_session:")]
        )

        # Clear anonymous entries
        cleared = manager.clear_all_anonymous()

        session_cache_after = len(
            [k for k in manager._cache if k.startswith("test_session:")]
        )

        assert cleared > 0, "Should have cleared anonymous entries"
        assert (
            session_cache_before == session_cache_after
        ), "Session-specific entries should be preserved"

    def test_anonymous_entries_not_cleaned_by_session_cleanup(
        self, manager: ThoughtSignatureManager
    ) -> None:
        """Test that anonymous entries are not cleaned by clear_session_cache()."""
        # Add anonymous entries
        anon_tool_calls = []
        for i in range(50):
            anon_tool_calls.append(
                {
                    "id": f"anon_tool_{i}",
                    "extra_content": {
                        "google": {"thought_signature": f"anon_sig_{i}"}
                    },
                }
            )

        manager.store_signatures_from_tool_calls(anon_tool_calls, None)

        initial_cache_size = len(manager._cache)

        # Try to clear with empty session_id (should not clear anonymous)
        cleared = manager.clear_session_cache("")

        final_cache_size = len(manager._cache)

        assert cleared == 0, "clear_session_cache('') should not clear anonymous entries"
        assert (
            final_cache_size == initial_cache_size
        ), "Anonymous entries should remain after clear_session_cache('')"

    def test_secondary_index_rebuilt_after_anonymous_cleanup(
        self, manager: ThoughtSignatureManager
    ) -> None:
        """Test that secondary index is properly rebuilt after anonymous cleanup."""
        # Add anonymous entries
        anon_tool_calls = []
        for i in range(100):
            anon_tool_calls.append(
                {
                    "id": f"anon_tool_{i}",
                    "extra_content": {
                        "google": {"thought_signature": f"anon_sig_{i}"}
                    },
                }
            )

        manager.store_signatures_from_tool_calls(anon_tool_calls, None)

        # Verify secondary index has entries
        initial_secondary_size = len(manager._by_tool_call)
        assert initial_secondary_size > 0, "Secondary index should have entries"

        # Clear anonymous entries
        manager.clear_all_anonymous()

        # Verify secondary index was rebuilt correctly
        final_secondary_size = len(manager._by_tool_call)

        # Secondary index should only contain entries from remaining cache
        # (which should be empty after clearing all anonymous)
        assert (
            final_secondary_size == 0
        ), "Secondary index should be empty after clearing all anonymous entries"

        # Verify no orphaned entries in secondary index
        for tc_id in manager._by_tool_call:
            # Check if any cache entry references this tool_call_id
            found = False
            for cache_key in manager._cache:
                if cache_key.endswith(f":{tc_id}") or cache_key == tc_id:
                    found = True
                    break
            assert found, (
                f"Orphaned entry in secondary index: {tc_id} "
                "not found in cache"
            )
