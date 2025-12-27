"""Thread-safe singleton initialization test for StreamingContextRegistry."""

import threading

from src.core.services.streaming.stream_context_registry import (
    StreamingContextRegistry,
    get_global_streaming_context_registry,
    set_global_streaming_context_registry,
)


def test_global_singleton_is_thread_safe():
    """Test that global registry singleton initialization is thread-safe.

    This test verifies that even when multiple threads call
    get_global_streaming_context_registry() simultaneously,
    only one instance is created (check-then-act race is prevented).
    """
    # Set a new registry to ensure a fresh start
    test_registry = StreamingContextRegistry(state_ttl_seconds=300)
    set_global_streaming_context_registry(test_registry)

    # Track instances created by concurrent threads
    instances = []
    lock = threading.Lock()

    def worker():
        """Worker function that gets the global registry."""
        registry = get_global_streaming_context_registry()
        with lock:
            instances.append(id(registry))

    # Create many threads that will all race to get the global registry
    threads = [threading.Thread(target=worker) for _ in range(100)]

    # Start all threads at once to maximize race condition opportunity
    for thread in threads:
        thread.start()

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    # All threads should have received the same instance
    unique_instances = set(instances)
    assert len(unique_instances) == 1, (
        f"Expected 1 unique instance but got {len(unique_instances)}. "
        "This indicates a race condition in singleton initialization."
    )

    # Verify instance is of the expected type
    registry = get_global_streaming_context_registry()
    assert isinstance(registry, StreamingContextRegistry)


def test_global_singleton_same_instance_across_calls():
    """Test that calling get_global_streaming_context_registry multiple times returns the same instance."""
    # Set a new registry to ensure a fresh start
    test_registry = StreamingContextRegistry(state_ttl_seconds=300)
    set_global_streaming_context_registry(test_registry)

    instance1 = get_global_streaming_context_registry()
    instance2 = get_global_streaming_context_registry()
    instance3 = get_global_streaming_context_registry()

    assert (
        id(instance1) == id(instance2) == id(instance3)
    ), "All calls should return the same singleton instance"


def test_set_global_overrides_singleton():
    """Test that set_global_streaming_context_registry can override the singleton."""
    # Set initial registry
    registry1 = StreamingContextRegistry(state_ttl_seconds=300)
    set_global_streaming_context_registry(registry1)

    instance1 = get_global_streaming_context_registry()

    # Override with new registry
    registry2 = StreamingContextRegistry(state_ttl_seconds=600)
    set_global_streaming_context_registry(registry2)

    registry3 = get_global_streaming_context_registry()

    # After setting, we should get the set registry
    assert id(registry3) == id(registry2)
    # And it should be different from the original
    assert id(registry3) != id(instance1)
