"""Regression test for ThoughtSignatureManager cache property getter/setter.

This test verifies that ThoughtSignatureManager cache property getter and setter
work correctly, maintaining backward compatibility while using internal OrderedDict
structure with timestamps.

Fixed: Cache property getter/setter properly converts between dict[str, str] and
OrderedDict[str, tuple[str, float]] formats.
"""

import pytest
from src.connectors.gemini_base.thought_signature_manager import ThoughtSignatureManager


class TestThoughtSignatureManagerCachePropertyRegression:
    """Regression tests for ThoughtSignatureManager cache property."""

    @pytest.fixture
    def manager(self) -> ThoughtSignatureManager:
        """Create ThoughtSignatureManager for testing."""
        return ThoughtSignatureManager(max_cache_size=1000, ttl_seconds=3600)

    def test_cache_property_getter(self, manager: ThoughtSignatureManager) -> None:
        """Test that cache property getter returns dict[str, str] format."""
        # Set cache via update method (cache property getter returns new dict each time)
        manager.update({"test_key": "test_value"})

        # Get cache via property
        retrieved_cache = manager.cache

        # Should be a dict[str, str]
        assert isinstance(retrieved_cache, dict), "Cache property should return dict"
        assert (
            retrieved_cache["test_key"] == "test_value"
        ), "Cache property getter should return correct value"

        # Internal cache should have tuple format
        assert isinstance(
            manager._cache["test_key"], tuple
        ), "Internal cache should store (signature, timestamp) tuples"
        assert (
            len(manager._cache["test_key"]) == 2
        ), "Internal cache tuple should have 2 elements"

    def test_cache_property_setter(self, manager: ThoughtSignatureManager) -> None:
        """Test that cache property setter accepts dict[str, str] format."""
        # Set cache via property with multiple entries
        test_cache = {
            "key1": "value1",
            "key2": "value2",
            "test_key": "updated_value",
        }
        manager.cache = test_cache

        # Verify internal cache structure
        assert (
            len(manager._cache) == 3
        ), "Internal cache should have 3 entries after setting"

        # Verify all entries have tuple format
        for key in test_cache:
            assert key in manager._cache, f"Key {key} should be in internal cache"
            assert isinstance(
                manager._cache[key], tuple
            ), f"Internal cache entry for {key} should be tuple"
            sig, timestamp = manager._cache[key]
            assert (
                sig == test_cache[key]
            ), f"Signature for {key} should match original value"
            assert isinstance(timestamp, float), f"Timestamp for {key} should be float"

        # Verify getter returns correct values
        retrieved_cache = manager.cache
        assert (
            retrieved_cache == test_cache
        ), "Cache property getter should return same values as setter"

    def test_cache_property_update(self, manager: ThoughtSignatureManager) -> None:
        """Test that cache property supports update() method."""
        # Set initial cache using update method
        manager.update({"initial_key": "initial_value"})

        # Update cache using update() method
        manager.update(
            {
                "key1": "value1",
                "key2": "value2",
                "initial_key": "updated_value",
            }
        )

        # Verify updates
        assert len(manager.cache) == 3, "Cache should have 3 entries after update"
        assert (
            manager.cache["initial_key"] == "updated_value"
        ), "Updated key should have new value"
        assert manager.cache["key1"] == "value1", "New key1 should be added"
        assert manager.cache["key2"] == "value2", "New key2 should be added"

    def test_cache_property_integration_with_service(
        self, manager: ThoughtSignatureManager
    ) -> None:
        """Test that cache property works with ThoughtSignatureService."""
        from src.connectors.gemini_base.thought_signature_service import (
            ThoughtSignatureService,
        )

        service = ThoughtSignatureService(use_global_cache=False)
        service._manager = manager

        # Set up cache as test expects using update method
        cache_key = "test_session_abc:call_test123"
        manager.update({cache_key: "cached_signature_xyz"})

        # Verify cache is set in manager
        assert (
            manager.cache[cache_key] == "cached_signature_xyz"
        ), "Manager cache should be set correctly"

        # Verify service can access cache through manager
        # The service uses manager.cache internally
        assert (
            service._manager.cache[cache_key] == "cached_signature_xyz"
        ), "Service should access manager cache correctly"

    def test_cache_property_preserves_internal_structure(
        self, manager: ThoughtSignatureManager
    ) -> None:
        """Test that cache property preserves internal OrderedDict structure."""
        # Set cache via property
        manager.cache = {
            "key1": "value1",
            "key2": "value2",
            "key3": "value3",
        }

        # Internal cache should be OrderedDict
        from collections import OrderedDict

        assert isinstance(
            manager._cache, OrderedDict
        ), "Internal cache should be OrderedDict"

        # Verify order is preserved (LRU order)
        keys = list(manager._cache.keys())
        assert keys == [
            "key1",
            "key2",
            "key3",
        ], "Cache keys should be in insertion order"

        # Access a key to move it to end (LRU behavior)
        _ = manager.cache["key1"]
        # Note: The getter doesn't modify LRU order, but accessing via _cache would
        # For this test, we verify the structure is maintained
