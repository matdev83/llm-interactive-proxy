"""
Repro script to test edge cases for memory leaks.

Edge cases to test:
1. Cache eviction race condition - adding entries faster than eviction
2. TTL cleanup that depends on access patterns
3. Cleanup that only runs conditionally
"""

import asyncio
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.services.buffered_wire_capture_service import BufferedWireCapture
from src.core.config.app_config import AppConfig
from src.core.services.rate_limiter import InMemoryRateLimiter


async def test_cache_eviction_race_condition():
    """Test if cache can exceed limit when entries are added rapidly."""
    print("\n" + "=" * 70)
    print("Edge Case 1: Cache eviction race condition")
    print("=" * 70)
    
    config = AppConfig()
    capture = BufferedWireCapture(config)
    capture._cache_max_size = 10  # Small limit for testing
    
    print(f"Cache max size: {capture._cache_max_size}")
    
    # Add entries rapidly in a tight loop
    # This simulates high-throughput scenario
    print("\nAdding 50 entries rapidly...")
    for i in range(50):
        # Create unique payloads with different object IDs
        payload = {"test": f"payload_{i}_{time.time()}", "data": "x" * 100}
        capture._get_content_length_cached(payload)
        
        cache_size = len(capture._content_length_cache)
        if cache_size > capture._cache_max_size:
            print(f"  [LEAK] After {i+1} additions: cache_size={cache_size} > max={capture._cache_max_size}")
            return True
        
        if (i + 1) % 10 == 0:
            print(f"  After {i+1} additions: cache_size={cache_size}")
    
    final_size = len(capture._content_length_cache)
    print(f"\nFinal cache size: {final_size}")
    
    if final_size > capture._cache_max_size:
        print(f"[LEAK CONFIRMED] Final cache size ({final_size}) exceeds limit ({capture._cache_max_size})")
        return True
    else:
        print("[OK] Cache size is within limits")
        return False


async def test_rate_limiter_cooldown_cleanup():
    """Test if cooldowns dict can grow unbounded if cleanup condition isn't met."""
    print("\n" + "=" * 70)
    print("Edge Case 2: Rate limiter cooldown cleanup")
    print("=" * 70)
    
    limiter = InMemoryRateLimiter()
    
    # Add many cooldowns but keep count just below cleanup threshold
    print("Adding cooldowns just below cleanup threshold (100)...")
    for i in range(95):  # Just below threshold
        await limiter.apply_cooldown(f"key_{i}", 60)
    
    cooldown_size = len(limiter._cooldowns)
    print(f"Cooldowns size after 95 additions: {cooldown_size}")
    
    # Now add more to trigger cleanup
    print("\nAdding more cooldowns to trigger cleanup...")
    for i in range(95, 150):
        await limiter.apply_cooldown(f"key_{i}", 60)
    
    final_size = len(limiter._cooldowns)
    print(f"Final cooldowns size: {final_size}")
    
    # Check if cleanup happened
    if final_size > 150:  # Should be cleaned up
        print(f"[POTENTIAL ISSUE] Cooldowns size ({final_size}) seems high")
        return True
    else:
        print("[OK] Cooldowns cleanup working")
        return False


async def test_rate_limiter_limits_cleanup():
    """Test if limits dict cleanup depends on access patterns."""
    print("\n" + "=" * 70)
    print("Edge Case 3: Rate limiter limits cleanup")
    print("=" * 70)
    
    limiter = InMemoryRateLimiter()
    
    # Set many limits but don't access them (to test TTL cleanup)
    print("Setting 1200 limits (above cleanup threshold of 1000)...")
    for i in range(1200):
        await limiter.set_limit(f"limit_key_{i}", 60, 60)
    
    limits_size = len(limiter._limits)
    print(f"Limits size after setting: {limits_size}")
    
    # Check if cleanup was triggered
    if limits_size > limiter._max_limits:
        print(f"[LEAK CONFIRMED] Limits size ({limits_size}) exceeds max ({limiter._max_limits})")
        return True
    
    # Now access some to trigger cleanup check
    print("\nAccessing some limits to trigger cleanup check...")
    for i in range(0, 1200, 100):
        await limiter.check_limit(f"limit_key_{i}")
    
    final_size = len(limiter._limits)
    print(f"Final limits size after access: {final_size}")
    
    if final_size > limiter._max_limits:
        print(f"[LEAK CONFIRMED] Final limits size ({final_size}) exceeds max ({limiter._max_limits})")
        return True
    else:
        print("[OK] Limits cleanup working")
        return False


async def main():
    """Run all edge case tests."""
    print("=" * 70)
    print("Memory Leak Edge Cases Testing")
    print("=" * 70)
    
    results = []
    
    results.append(await test_cache_eviction_race_condition())
    results.append(await test_rate_limiter_cooldown_cleanup())
    results.append(await test_rate_limiter_limits_cleanup())
    
    print("\n" + "=" * 70)
    print("Summary:")
    print("=" * 70)
    
    leaks_found = sum(results)
    if leaks_found > 0:
        print(f"[WARNING] Found {leaks_found} potential edge case issues")
    else:
        print("[OK] No edge case issues detected")
    
    return leaks_found > 0


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(1 if result else 0)
