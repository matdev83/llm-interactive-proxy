"""
Repro script to test max limit in stream context registry.

Tests that max limit prevents unbounded growth even when streams are never accessed again.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.services.streaming.stream_context_registry import StreamingContextRegistry


def test_max_limit_enforcement():
    """Test that max limit prevents unbounded growth."""
    print("\n" + "=" * 70)
    print("Test: Stream context registry max limit")
    print("=" * 70)
    
    registry = StreamingContextRegistry(state_ttl_seconds=300)
    max_limit = registry._MAX_STREAM_STATES
    
    print(f"Max stream states limit: {max_limit}")
    
    # Create more streams than the limit
    print(f"\nCreating {max_limit + 100} streams...")
    for i in range(max_limit + 100):
        stream_id = f"stream_{i}"
        registry.get_content_state(stream_id)
        
        states_size = len(registry._states)
        if states_size > max_limit:
            print(f"  [LEAK] After {i+1} additions: states_size={states_size} > max={max_limit}")
            return True
        
        if (i + 1) % 2000 == 0:
            print(f"  After {i+1} additions: states_size={states_size}")
    
    final_size = len(registry._states)
    print(f"\nFinal states size: {final_size}")
    
    if final_size > max_limit:
        print(f"[LEAK CONFIRMED] Final states size ({final_size}) exceeds max ({max_limit})")
        return True
    else:
        print(f"[OK] States size ({final_size}) is within max limit ({max_limit})")
        return False


def main():
    """Run test."""
    print("=" * 70)
    print("Memory Leak Test: Stream Context Registry Max Limit")
    print("=" * 70)
    
    leak_confirmed = test_max_limit_enforcement()
    
    print("\n" + "=" * 70)
    print("Summary:")
    print("=" * 70)
    if leak_confirmed:
        print("[WARNING] Max limit not enforced properly")
    else:
        print("[OK] Max limit enforced correctly")
    
    return leak_confirmed


if __name__ == "__main__":
    result = main()
    sys.exit(1 if result else 0)
