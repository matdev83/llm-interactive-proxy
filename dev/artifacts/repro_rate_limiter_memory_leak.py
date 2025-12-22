"""Repro script to demonstrate memory leak in InMemoryRateLimiter.

The issue: The rate limiter accumulates keys in _usage, _limits, and _cooldowns
dictionaries without cleanup. Even when all timestamps expire for a key, the key
remains in the dictionary, causing unbounded memory growth.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.services.rate_limiter import InMemoryRateLimiter


async def main():
    """Demonstrate unbounded memory growth in rate limiter."""
    limiter = InMemoryRateLimiter(default_limit=10, default_time_window=1)

    print("=" * 80)
    print("Memory Leak Repro: InMemoryRateLimiter")
    print("=" * 80)
    print()

    # Initial state
    print(f"Initial state:")
    print(f"  _usage keys: {len(limiter._usage)}")
    print(f"  _limits keys: {len(limiter._limits)}")
    print(f"  _cooldowns keys: {len(limiter._cooldowns)}")
    print()

    # Simulate many unique keys being used
    num_keys = 1000
    print(f"Simulating {num_keys} unique keys...")

    for i in range(num_keys):
        key = f"user_{i}"
        # Record usage
        await limiter.record_usage(key, cost=1)
        # Check limit (this filters expired timestamps but doesn't remove empty keys)
        await limiter.check_limit(key)

    print(f"After recording usage for {num_keys} keys:")
    print(f"  _usage keys: {len(limiter._usage)}")
    print(f"  _limits keys: {len(limiter._limits)}")
    print(f"  _cooldowns keys: {len(limiter._cooldowns)}")
    print()

    # Wait for all timestamps to expire
    print("Waiting for timestamps to expire (2 seconds)...")
    await asyncio.sleep(2)

    # Check limits again - this should filter expired timestamps
    print("Checking limits again (should filter expired timestamps)...")
    for i in range(min(100, num_keys)):  # Check a sample
        key = f"user_{i}"
        await limiter.check_limit(key)

    print(f"After expiration and re-checking:")
    print(f"  _usage keys: {len(limiter._usage)} (should be 0, but is {len(limiter._usage)})")
    print(f"  _limits keys: {len(limiter._limits)}")
    print(f"  _cooldowns keys: {len(limiter._cooldowns)}")
    print()

    # Count empty lists in _usage
    empty_keys = sum(1 for timestamps in limiter._usage.values() if len(timestamps) == 0)
    print(f"Empty timestamp lists in _usage: {empty_keys}")
    print()

    # Set custom limits for many keys
    print(f"Setting custom limits for {num_keys} keys...")
    for i in range(num_keys):
        key = f"user_{i}"
        await limiter.set_limit(key, limit=20, time_window=60)

    print(f"After setting custom limits:")
    print(f"  _limits keys: {len(limiter._limits)} (should be {num_keys})")
    print()

    # Apply cooldowns
    print(f"Applying cooldowns for {num_keys} keys...")
    for i in range(num_keys):
        key = f"user_{i}"
        await limiter.apply_cooldown(key, cooldown_seconds=1)

    print(f"After applying cooldowns:")
    print(f"  _cooldowns keys: {len(limiter._cooldowns)}")
    print()

    # Wait for cooldowns to expire
    print("Waiting for cooldowns to expire (2 seconds)...")
    await asyncio.sleep(2)

    # Only check a few keys - others will remain in _cooldowns forever
    print("Checking limits for only 10 keys (others remain in _cooldowns)...")
    for i in range(10):
        key = f"user_{i}"
        await limiter.check_limit(key)

    print(f"After cooldown expiration (only 10 keys checked):")
    print(f"  _cooldowns keys: {len(limiter._cooldowns)} (should be ~{num_keys - 10}, but many remain)")
    print()

    print("=" * 80)
    print("CONCLUSION: Memory leak confirmed!")
    print("=" * 80)
    print("1. _usage accumulates keys even when all timestamps expire")
    print("2. _limits accumulates keys without cleanup")
    print("3. _cooldowns accumulates keys that are never checked again")
    print()
    print("Expected behavior: Keys should be removed when:")
    print("  - All timestamps expire (for _usage)")
    print("  - Cooldown expires and key is checked (for _cooldowns)")
    print("  - Periodic cleanup runs (for all dicts)")


if __name__ == "__main__":
    asyncio.run(main())
