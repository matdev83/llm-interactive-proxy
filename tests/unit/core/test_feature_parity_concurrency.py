"""Test for FeatureParityRegistry global singleton thread safety."""

import threading

import pytest
from src.core.interfaces.feature_parity import (
    get_global_registry,
    reset_global_registry,
)


class TestFeatureParityRegistryConcurrency:
    """Tests for FeatureParityRegistry thread-safety."""

    def setup_method(self):
        """Reset registry before each test."""
        reset_global_registry()

    def teardown_method(self):
        """Reset registry after each test."""
        reset_global_registry()

    def test_concurrent_get_global_registry_safety(self):
        """Test that concurrent calls to get_global_registry are thread-safe.

        Without proper synchronization, multiple threads can create
        multiple instances, breaking the singleton contract.
        """
        registry_instances = []

        def get_instance():
            reg = get_global_registry()
            registry_instances.append(id(reg))

        # Create multiple threads that all try to get the registry
        threads = []
        for _ in range(10):
            t = threading.Thread(target=get_instance)
            threads.append(t)

        # Start all threads
        for t in threads:
            t.start()

        # Wait for all threads to complete
        for t in threads:
            t.join()

        # All calls should return the same instance
        unique_instances = set(registry_instances)
        assert len(unique_instances) == 1, (
            f"Expected 1 unique instance but got {len(unique_instances)}. "
            f"This indicates a race condition in get_global_registry()."
        )


if __name__ == "__main__":
    import threading
    pytest.main([__file__, "-v"])
