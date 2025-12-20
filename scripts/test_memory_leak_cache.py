"""
Test script to demonstrate memory leak in BufferedWireCapture cache.

The issue: _content_length_cache uses id(payload) as keys. When objects
are garbage collected, their IDs can be reused, but cache entries remain.
This causes memory to grow unbounded over time.
"""

import asyncio
import gc
import sys
from unittest.mock import Mock

# Add src to path
sys.path.insert(0, "src")

from src.core.config.app_config import AppConfig
from src.core.services.buffered_wire_capture_service import BufferedWireCapture


async def test_cache_leak():
    """Test that cache grows unbounded with unique payloads."""
    # Create a temporary config
    config = Mock(spec=AppConfig)
    config.logging = Mock()
    config.logging.capture_file = None  # Disable file writing

    service = BufferedWireCapture(config)

    print(f"Initial cache size: {len(service._content_length_cache)}")
    print(f"Cache max size: {service._cache_max_size}")

    # Create many unique payload objects
    initial_cache_size = len(service._content_length_cache)
    cache_sizes = [initial_cache_size]

    for i in range(2000):  # Create 2000 unique payloads
        # Create a new dict object each time (unique id)
        payload = {"test": f"data_{i}", "items": list(range(i % 100))}

        # Call the cached method
        service._get_content_length_cached(payload)

        # Force garbage collection periodically
        if i % 100 == 0:
            gc.collect()
            cache_size = len(service._content_length_cache)
            cache_sizes.append(cache_size)
            print(f"Iteration {i}: Cache size = {cache_size}")

            # Check if cache exceeds limit
            if cache_size > service._cache_max_size:
                print(
                    f"⚠️  LEAK DETECTED: Cache size {cache_size} exceeds limit {service._cache_max_size}"
                )
                return True

    final_cache_size = len(service._content_length_cache)
    print(f"\nFinal cache size: {final_cache_size}")
    print(f"Cache growth: {final_cache_size - initial_cache_size}")

    # The cache should be bounded, but if it grows beyond max_size, it's a leak
    if final_cache_size > service._cache_max_size:
        print(
            f"❌ MEMORY LEAK CONFIRMED: Cache grew to {final_cache_size}, limit is {service._cache_max_size}"
        )
        return True
    else:
        print("✅ Cache is properly bounded")
        return False

    await service.shutdown()


if __name__ == "__main__":
    leak_found = asyncio.run(test_cache_leak())
    sys.exit(1 if leak_found else 0)
