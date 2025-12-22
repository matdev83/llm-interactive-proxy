"""
Repro script to confirm memory leak in BufferedWireCapture cache.

Issue: _content_length_cache only removes one entry at a time when limit is reached.
If entries are added faster than they're evicted, memory can grow unbounded.

Also: _json_cache is initialized but never used (dead code).
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.config.app_config import AppConfig
from src.core.services.buffered_wire_capture_service import BufferedWireCapture


async def test_cache_growth():
    """Test that cache grows unbounded when entries are added rapidly."""
    # Create minimal config
    config = AppConfig()
    
    # Create capture service with small cache limit for testing
    capture = BufferedWireCapture(config)
    capture._cache_max_size = 100  # Small limit for testing
    
    print(f"Initial cache size: {len(capture._content_length_cache)}")
    print(f"Cache max size: {capture._cache_max_size}")
    
    # Simulate rapid addition of unique payloads
    # Each payload gets a new object id, so cache will grow
    print("\nAdding 200 unique payloads rapidly...")
    for i in range(200):
        payload = {"test": f"payload_{i}", "data": "x" * 100}
        capture._get_content_length_cached(payload)
        
        if (i + 1) % 50 == 0:
            cache_size = len(capture._content_length_cache)
            print(f"  After {i+1} additions: cache_size={cache_size}, max={capture._cache_max_size}")
            
            # Check if cache exceeded limit
            if cache_size > capture._cache_max_size:
                print(f"  [WARNING]  MEMORY LEAK CONFIRMED: Cache size ({cache_size}) exceeds limit ({capture._cache_max_size})")
                return True
    
    final_size = len(capture._content_length_cache)
    print(f"\nFinal cache size: {final_size}")
    
    if final_size > capture._cache_max_size:
        print(f"[WARNING]  MEMORY LEAK CONFIRMED: Final cache size ({final_size}) exceeds limit ({capture._cache_max_size})")
        return True
    else:
        print("[OK] Cache size is within limits")
        return False


def test_unused_json_cache():
    """Test that _json_cache is never used (dead code)."""
    config = AppConfig()
    capture = BufferedWireCapture(config)
    
    print(f"\n_json_cache initialized: {capture._json_cache is not None}")
    print(f"Initial _json_cache size: {len(capture._json_cache)}")
    
    # Check if _serialize_entry_cached uses the cache
    from src.core.services.buffered_wire_capture_service import WireCaptureEntry
    from datetime import datetime, timezone
    import time
    
    entry = WireCaptureEntry(
        timestamp_iso=datetime.now(timezone.utc).isoformat(),
        timestamp_unix=time.time(),
        sequence=1,
        direction="test",
        source="test",
        destination="test",
        session_id="test",
        backend="test",
        model="test",
        key_name=None,
        content_type="json",
        content_length=0,
        payload={"test": "data"},
        metadata={},
    )
    
    # Call serialize multiple times - cache should grow if it's used
    initial_cache_size = len(capture._json_cache)
    for _ in range(10):
        capture._serialize_entry_cached(entry)
    
    final_cache_size = len(capture._json_cache)
    
    print(f"After 10 serializations: _json_cache size={final_cache_size}")
    
    if final_cache_size == initial_cache_size:
        print("[WARNING]  DEAD CODE CONFIRMED: _json_cache is never used")
        return True
    else:
        print("✓ _json_cache is being used")
        return False


async def main():
    """Run all tests."""
    print("=" * 70)
    print("Memory Leak Repro: BufferedWireCapture Cache")
    print("=" * 70)
    
    leak_confirmed = await test_cache_growth()
    dead_code_confirmed = test_unused_json_cache()
    
    print("\n" + "=" * 70)
    print("Summary:")
    print("=" * 70)
    if leak_confirmed:
        print("[WARNING]  MEMORY LEAK CONFIRMED: Cache can grow beyond limit")
    else:
        print("[OK] No memory leak detected in cache eviction")
    
    if dead_code_confirmed:
        print("[WARNING]  DEAD CODE CONFIRMED: _json_cache is never used")
    else:
        print("✓ _json_cache is being used")
    
    return leak_confirmed or dead_code_confirmed


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(1 if result else 0)
