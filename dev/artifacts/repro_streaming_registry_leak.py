"""Repro script to demonstrate memory leak in StreamingContextRegistry.

The issue: cleanup_expired() is only called when ContentAccumulationProcessor.process()
is called. If no content is being processed, expired stream states accumulate indefinitely.
"""

import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.services.streaming.stream_context_registry import StreamingContextRegistry


def test_memory_leak():
    """Demonstrate that expired states accumulate if cleanup_expired() is not called."""
    registry = StreamingContextRegistry(state_ttl_seconds=1)  # Very short TTL for testing
    
    # Create many stream states
    print("Creating 100 stream states...")
    for i in range(100):
        stream_id = f"stream-{i}"
        registry.get_content_state(stream_id)
    
    print(f"Initial state count: {len(registry._states)}")
    assert len(registry._states) == 100, f"Expected 100 states, got {len(registry._states)}"
    
    # Wait for TTL to expire
    print("Waiting for TTL to expire (2 seconds)...")
    time.sleep(2)
    
    # Check state count - should be 0 if cleanup was called, but it won't be
    print(f"State count after TTL expiration (without calling cleanup_expired): {len(registry._states)}")
    
    # States are still there because cleanup_expired() was never called
    assert len(registry._states) == 100, f"Expected 100 states (leak!), got {len(registry._states)}"
    print("[CONFIRMED] Memory leak - expired states are not cleaned up automatically")
    
    # Now manually call cleanup_expired()
    registry.cleanup_expired()
    print(f"State count after manual cleanup_expired(): {len(registry._states)}")
    assert len(registry._states) == 0, f"Expected 0 states after cleanup, got {len(registry._states)}"
    print("[OK] After manual cleanup, states are removed")
    
    # Simulate the real-world scenario: streams created but processing stops
    print("\nSimulating real-world scenario: streams created but processing stops...")
    for i in range(50):
        stream_id = f"abandoned-stream-{i}"
        registry.get_content_state(stream_id)
    
    print(f"Created 50 stream states")
    print(f"State count: {len(registry._states)}")
    
    # Wait for expiration
    time.sleep(2)
    
    # In real code, if no ContentAccumulationProcessor.process() is called,
    # cleanup_expired() is never called, so states accumulate
    print(f"State count after expiration (no cleanup called): {len(registry._states)}")
    assert len(registry._states) == 50, "States should still be there (leak!)"
    print("[CONFIRMED] Memory leak - states accumulate if processing stops")
    
    return True


if __name__ == "__main__":
    print("=" * 70)
    print("Memory Leak Repro: StreamingContextRegistry")
    print("=" * 70)
    test_memory_leak()
    print("\n" + "=" * 70)
    print("Memory leak confirmed!")
    print("=" * 70)
