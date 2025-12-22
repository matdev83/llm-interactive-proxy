"""
Repro script to test edge case in stream context registry TTL cleanup.

Edge case: TTL cleanup only runs on access (_maybe_cleanup_expired).
If streams are created but never accessed again, they won't be cleaned up
until something else triggers cleanup or they're accessed.

This could lead to memory leaks if:
1. Many streams are created but never accessed
2. Cleanup is never triggered by other operations
"""

import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.services.streaming.stream_context_registry import StreamingContextRegistry


def test_ttl_cleanup_on_access_only():
    """Test if TTL cleanup only happens on access."""
    print("\n" + "=" * 70)
    print("Edge Case: Stream context TTL cleanup")
    print("=" * 70)
    
    registry = StreamingContextRegistry(state_ttl_seconds=1)  # Very short TTL for testing
    
    print(f"TTL: {registry._ttl_seconds} seconds")
    
    # Create many streams
    print("\nCreating 50 streams...")
    for i in range(50):
        stream_id = f"stream_{i}"
        registry.get_content_state(stream_id)
    
    initial_size = len(registry._states)
    print(f"Initial states size: {initial_size}")
    
    # Wait for TTL to expire
    print("\nWaiting for TTL to expire (2 seconds)...")
    time.sleep(2)
    
    # Check size without accessing - cleanup shouldn't happen
    size_before_access = len(registry._states)
    print(f"States size before access: {size_before_access}")
    
    if size_before_access == initial_size:
        print("[POTENTIAL ISSUE] States not cleaned up without access")
    
    # Now access one stream - this should trigger cleanup
    print("\nAccessing one stream (should trigger cleanup)...")
    registry.get_content_state("stream_0")
    
    size_after_access = len(registry._states)
    print(f"States size after access: {size_after_access}")
    
    if size_after_access < size_before_access:
        print("[OK] Cleanup triggered on access")
        return False
    else:
        print(f"[ISSUE] Cleanup didn't remove expired states (before: {size_before_access}, after: {size_after_access})")
        return True


def test_orphaned_streams():
    """Test if streams that are never accessed again accumulate."""
    print("\n" + "=" * 70)
    print("Edge Case: Orphaned streams")
    print("=" * 70)
    
    registry = StreamingContextRegistry(state_ttl_seconds=300)  # 5 minutes
    
    # Create many streams but only access first few
    print("Creating 100 streams, accessing only first 10...")
    for i in range(100):
        stream_id = f"orphan_stream_{i}"
        registry.get_content_state(stream_id)
    
    # Only access first 10 repeatedly
    for _ in range(10):
        for i in range(10):
            registry.get_content_state(f"orphan_stream_{i}")
    
    final_size = len(registry._states)
    print(f"Final states size: {final_size}")
    
    # Check if orphaned streams (11-100) are still there
    orphaned_count = sum(
        1 for sid in registry._states.keys()
        if sid.startswith("orphan_stream_") and int(sid.split("_")[-1]) >= 10
    )
    
    print(f"Orphaned streams (never accessed again): {orphaned_count}")
    
    if orphaned_count > 0:
        print(f"[POTENTIAL ISSUE] {orphaned_count} orphaned streams still in registry")
        # They should be cleaned up by TTL eventually, but if TTL is long and many streams are created,
        # this could accumulate
        return True
    else:
        print("[OK] Orphaned streams cleaned up")
        return False


def main():
    """Run all tests."""
    print("=" * 70)
    print("Memory Leak Edge Cases: Stream Context Registry")
    print("=" * 70)
    
    results = []
    results.append(test_ttl_cleanup_on_access_only())
    results.append(test_orphaned_streams())
    
    print("\n" + "=" * 70)
    print("Summary:")
    print("=" * 70)
    
    issues_found = sum(results)
    if issues_found > 0:
        print(f"[WARNING] Found {issues_found} potential edge case issues")
    else:
        print("[OK] No edge case issues detected")
    
    return issues_found > 0


if __name__ == "__main__":
    result = main()
    sys.exit(1 if result else 0)
