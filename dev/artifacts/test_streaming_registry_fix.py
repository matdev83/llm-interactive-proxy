"""Test script to verify the memory leak fix for StreamingContextRegistry."""

import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.services.streaming.stream_context_registry import StreamingContextRegistry


def test_fix():
    """Verify that expired states are cleaned up automatically on access."""
    registry = StreamingContextRegistry(
        state_ttl_seconds=1
    )  # Very short TTL for testing

    # Create many stream states
    print("Creating 100 stream states...")
    for i in range(100):
        stream_id = f"stream-{i}"
        registry.get_content_state(stream_id)

    print(f"Initial state count: {len(registry._states)}")
    assert (
        len(registry._states) == 100
    ), f"Expected 100 states, got {len(registry._states)}"

    # Wait for TTL to expire
    print("Waiting for TTL to expire (2 seconds)...")
    time.sleep(2)

    # Access the registry - this should trigger cleanup
    print("Accessing registry (should trigger cleanup)...")
    registry.get_content_state("new-stream")

    # Check state count - should be 1 (only the new stream)
    print(f"State count after accessing registry: {len(registry._states)}")
    assert (
        len(registry._states) == 1
    ), f"Expected 1 state after cleanup, got {len(registry._states)}"
    print("[OK] Expired states were automatically cleaned up on access")

    # Test that accessing any method triggers cleanup
    print("\nTesting cleanup on different access methods...")
    for i in range(10):
        stream_id = f"test-stream-{i}"
        registry.get_tool_call_buffer(stream_id)
        registry.get_json_repair_buffer(stream_id)
        registry.get_vtc_buffer(stream_id)

    print(f"Created 10 more streams, state count: {len(registry._states)}")
    assert (
        len(registry._states) == 11
    ), f"Expected 11 states, got {len(registry._states)}"

    # Wait for expiration
    time.sleep(2)

    # Access via any method should trigger cleanup
    # This will clean up expired states and create a new one for test-stream-0
    registry.get_fragment("test-stream-0", "test-ns")
    print(f"State count after accessing expired streams: {len(registry._states)}")
    # Should be 1 (test-stream-0 we just accessed, which creates a new state)
    # The "new-stream" from before should be expired and cleaned up
    assert (
        len(registry._states) == 1
    ), f"Expected 1 state after cleanup, got {len(registry._states)}"
    assert (
        "test-stream-0" in registry._states
    ), "test-stream-0 should be the remaining state"
    print("[OK] Cleanup triggered on all access methods")

    return True


if __name__ == "__main__":
    print("=" * 70)
    print("Memory Leak Fix Verification: StreamingContextRegistry")
    print("=" * 70)
    test_fix()
    print("\n" + "=" * 70)
    print("Fix verified - memory leak resolved!")
    print("=" * 70)
