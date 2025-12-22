"""Test script to verify rate limiter memory leak fix."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.services.rate_limiter import InMemoryRateLimiter


async def test_fix():
    """Test that memory leak is fixed."""
    limiter = InMemoryRateLimiter(default_limit=10, default_time_window=1)

    print("=" * 80)
    print("Testing Rate Limiter Memory Leak Fix")
    print("=" * 80)
    print()

    # Test 1: Empty timestamp lists should be removed
    print("Test 1: Empty timestamp lists should be removed")
    num_keys = 100
    for i in range(num_keys):
        key = f"user_{i}"
        await limiter.record_usage(key, cost=1)

    print(f"  Created {num_keys} keys with usage")
    print(f"  _usage keys: {len(limiter._usage)}")

    # Wait for expiration
    await asyncio.sleep(2)

    # Check limits - should remove empty lists
    for i in range(num_keys):
        key = f"user_{i}"
        await limiter.check_limit(key)

    print(f"  After expiration and re-checking:")
    print(f"  _usage keys: {len(limiter._usage)} (should be 0)")
    assert len(limiter._usage) == 0, f"Expected 0 keys, got {len(limiter._usage)}"
    print("  [PASSED]")
    print()

    # Test 2: Custom limits should be removed when usage expires
    print("Test 2: Custom limits should be removed when usage expires")
    for i in range(50):
        key = f"limit_user_{i}"
        # Use default time_window (1 second) so timestamps expire quickly
        await limiter.set_limit(key, limit=20, time_window=1)
        await limiter.record_usage(key, cost=1)

    print(f"  Created 50 keys with custom limits (1s window)")
    print(f"  _limits keys: {len(limiter._limits)}")

    # Wait for expiration (longer than 1s window)
    await asyncio.sleep(2)

    # Check limits - should remove usage and limits
    for i in range(50):
        key = f"limit_user_{i}"
        await limiter.check_limit(key)

    print(f"  After expiration:")
    print(f"  _usage keys: {len(limiter._usage)} (should be 0)")
    print(f"  _limits keys: {len(limiter._limits)} (should be 0)")
    assert len(limiter._usage) == 0, f"Expected 0 usage keys, got {len(limiter._usage)}"
    assert len(limiter._limits) == 0, f"Expected 0 limit keys, got {len(limiter._limits)}"
    print("  [PASSED]")
    print()

    # Test 3: Expired cooldowns should be cleaned up periodically
    print("Test 3: Expired cooldowns should be cleaned up periodically")
    for i in range(200):
        key = f"cooldown_user_{i}"
        await limiter.apply_cooldown(key, cooldown_seconds=1)

    print(f"  Created 200 cooldowns")
    print(f"  _cooldowns keys: {len(limiter._cooldowns)}")

    # Wait for expiration
    await asyncio.sleep(2)

    # Check a few keys to trigger cleanup
    for i in range(10):
        key = f"cooldown_user_{i}"
        await limiter.check_limit(key)

    # Check more keys to trigger cleanup on different hash buckets
    for i in range(100, 150):
        key = f"cooldown_user_{i}"
        await limiter.check_limit(key)

    print(f"  After expiration and checking some keys:")
    print(f"  _cooldowns keys: {len(limiter._cooldowns)} (should be < 200)")
    # Should have cleaned up at least some expired cooldowns
    assert len(limiter._cooldowns) < 200, f"Expected < 200 cooldowns, got {len(limiter._cooldowns)}"
    print("  [PASSED]")
    print()

    # Test 4: Reset should remove keys
    print("Test 4: Reset should remove keys")
    for i in range(20):
        key = f"reset_user_{i}"
        await limiter.record_usage(key, cost=1)
        await limiter.set_limit(key, limit=30, time_window=60)

    print(f"  Created 20 keys")
    print(f"  _usage keys: {len(limiter._usage)}")
    print(f"  _limits keys: {len(limiter._limits)}")

    # Reset all
    for i in range(20):
        key = f"reset_user_{i}"
        await limiter.reset(key)

    print(f"  After reset:")
    print(f"  _usage keys: {len(limiter._usage)} (should be 0)")
    print(f"  _limits keys: {len(limiter._limits)} (should be 20, limits persist)")
    assert len(limiter._usage) == 0, f"Expected 0 usage keys, got {len(limiter._usage)}"
    # Limits persist by design (they're configuration)
    print("  [PASSED]")
    print()

    print("=" * 80)
    print("All tests passed! Memory leak fix verified.")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_fix())
