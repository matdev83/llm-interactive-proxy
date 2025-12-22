"""Repro script to demonstrate memory leak in InMemoryRateLimiter._limits.

The issue: The _limits dictionary can grow unbounded when set_limit() is called
for many unique keys without ever calling check_limit() or record_usage() for
those keys. The cleanup logic in check_limit() only removes limits when usage
data exists and expires, but if a limit is set and never used, it remains forever.
"""

import asyncio
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.services.rate_limiter import InMemoryRateLimiter


async def main():
    """Demonstrate unbounded memory growth in rate limiter _limits dict."""
    limiter = InMemoryRateLimiter(default_limit=10, default_time_window=60)

    print("=" * 80)
    print("Memory Leak Repro: InMemoryRateLimiter._limits")
    print("=" * 80)
    print()

    # Initial state
    print(f"Initial state:")
    print(f"  _limits keys: {len(limiter._limits)}")
    print(f"  _usage keys: {len(limiter._usage)}")
    print()

    # Simulate many unique keys having limits set without ever being used
    num_keys = 10000
    print(f"Setting custom limits for {num_keys} unique keys WITHOUT using them...")
    print("(This simulates a scenario where limits are configured but never checked)")

    for i in range(num_keys):
        key = f"unused_key_{i}"
        await limiter.set_limit(key, limit=20, time_window=60)

    print(f"After setting {num_keys} limits:")
    print(f"  _limits keys: {len(limiter._limits)}")
    print(f"  _usage keys: {len(limiter._usage)}")
    print()

    # Now check limits for only a few keys
    print("Checking limits for only 10 keys (others remain in _limits forever)...")
    for i in range(10):
        key = f"unused_key_{i}"
        await limiter.check_limit(key)

    print(f"After checking limits for 10 keys:")
    print(f"  _limits keys: {len(limiter._limits)} (should be {num_keys}, all remain)")
    print(f"  _usage keys: {len(limiter._usage)}")
    print()

    # Even if we check all keys, limits remain because they're custom limits
    print("Checking limits for all keys...")
    for i in range(num_keys):
        key = f"unused_key_{i}"
        await limiter.check_limit(key)

    print(f"After checking limits for all keys:")
    print(f"  _limits keys: {len(limiter._limits)} (should be {num_keys}, all remain)")
    print(f"  _usage keys: {len(limiter._usage)}")
    print()

    # Wait for timestamps to expire
    print("Waiting for timestamps to expire (65 seconds)...")
    await asyncio.sleep(65)

    # Check limits again - usage should be cleaned up, but limits remain
    print("Checking limits again after expiration...")
    for i in range(min(100, num_keys)):
        key = f"unused_key_{i}"
        await limiter.check_limit(key)

    print(f"After expiration and re-checking:")
    print(f"  _limits keys: {len(limiter._limits)} (should be {num_keys}, all remain)")
    print(f"  _usage keys: {len(limiter._usage)} (should be 0 or small)")
    print()

    # Test max limits eviction
    print("Testing max limits eviction...")
    print(f"Max limits: {limiter._max_limits}")
    print(f"Current limits: {len(limiter._limits)}")
    print()

    # Try to add more limits beyond max - should evict oldest
    print(f"Adding {limiter._max_limits + 1000} more unique limits...")
    for i in range(num_keys, num_keys + limiter._max_limits + 1000):
        key = f"unused_key_{i}"
        await limiter.set_limit(key, limit=20, time_window=60)

    print(f"After adding beyond max:")
    print(f"  _limits keys: {len(limiter._limits)} (should be <= {limiter._max_limits})")
    print(f"  _limits_last_access keys: {len(limiter._limits_last_access)}")
    print()

    # Test TTL cleanup by manually setting old access times
    print("Testing TTL cleanup with old access times...")
    old_time = time.time() - (limiter._limits_ttl_seconds + 3600)  # 25 hours ago
    # Set some keys to have old access times
    for i, key in enumerate(list(limiter._limits.keys())[:1000]):
        limiter._limits_last_access[key] = old_time

    await limiter._cleanup_unused_limits_locked(time.time())
    print(f"After TTL cleanup:")
    print(f"  _limits keys: {len(limiter._limits)} (should be reduced)")
    print()

    print("=" * 80)
    if len(limiter._limits) <= limiter._max_limits:
        print("SUCCESS: Memory leak fixed!")
        print("Limits are now cleaned up based on TTL and max size limits.")
        print(f"Final limits count: {len(limiter._limits)} (max: {limiter._max_limits})")
    else:
        print("Memory leak still present!")
        print(f"Expected <= {limiter._max_limits} limits, got {len(limiter._limits)}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
