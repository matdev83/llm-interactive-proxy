"""
Repro script to test edge case in rate limiter limits eviction.

Edge case: set_limit() only evicts when adding NEW keys, not when replacing.
If we're at max_limits and replace an existing key, no eviction happens.
But more importantly, if we add many new keys rapidly, eviction might not keep up.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.services.rate_limiter import InMemoryRateLimiter


async def test_limits_eviction_edge_case():
    """Test if limits can exceed max when adding new keys rapidly."""
    print("\n" + "=" * 70)
    print("Edge Case: Rate limiter limits eviction")
    print("=" * 70)
    
    limiter = InMemoryRateLimiter()
    limiter._max_limits = 100  # Small limit for testing
    
    print(f"Max limits: {limiter._max_limits}")
    
    # Add many new limits rapidly
    print("\nAdding 150 new limits rapidly...")
    for i in range(150):
        await limiter.set_limit(f"limit_key_{i}", 60, 60)
        
        limits_size = len(limiter._limits)
        if limits_size > limiter._max_limits:
            print(f"  [LEAK] After {i+1} additions: limits_size={limits_size} > max={limiter._max_limits}")
            return True
        
        if (i + 1) % 25 == 0:
            print(f"  After {i+1} additions: limits_size={limits_size}")
    
    final_size = len(limiter._limits)
    print(f"\nFinal limits size: {final_size}")
    
    if final_size > limiter._max_limits:
        print(f"[LEAK CONFIRMED] Final limits size ({final_size}) exceeds max ({limiter._max_limits})")
        return True
    else:
        print("[OK] Limits size is within bounds")
        return False


async def test_limits_eviction_replacement_edge_case():
    """Test if limits can grow when replacing existing keys."""
    print("\n" + "=" * 70)
    print("Edge Case: Rate limiter limits replacement")
    print("=" * 70)
    
    limiter = InMemoryRateLimiter()
    limiter._max_limits = 100
    
    # Fill up to max
    print("Filling limits to max...")
    for i in range(100):
        await limiter.set_limit(f"key_{i}", 60, 60)
    
    print(f"Limits size after filling: {len(limiter._limits)}")
    
    # Now replace all existing keys - this should NOT trigger eviction
    print("\nReplacing all existing limits...")
    for i in range(100):
        await limiter.set_limit(f"key_{i}", 70, 70)  # Different values
    
    size_after_replace = len(limiter._limits)
    print(f"Limits size after replacement: {size_after_replace}")
    
    # Now add NEW keys - this SHOULD trigger eviction
    print("\nAdding new limits (should trigger eviction)...")
    for i in range(100, 150):
        await limiter.set_limit(f"key_{i}", 60, 60)
        
        limits_size = len(limiter._limits)
        if limits_size > limiter._max_limits:
            print(f"  [LEAK] After adding key_{i}: limits_size={limits_size} > max={limiter._max_limits}")
            return True
    
    final_size = len(limiter._limits)
    print(f"\nFinal limits size: {final_size}")
    
    if final_size > limiter._max_limits:
        print(f"[LEAK CONFIRMED] Final limits size ({final_size}) exceeds max ({limiter._max_limits})")
        return True
    else:
        print("[OK] Limits eviction working correctly")
        return False


async def main():
    """Run all edge case tests."""
    print("=" * 70)
    print("Memory Leak Edge Cases: Rate Limiter Limits")
    print("=" * 70)
    
    results = []
    results.append(await test_limits_eviction_edge_case())
    results.append(await test_limits_eviction_replacement_edge_case())
    
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
