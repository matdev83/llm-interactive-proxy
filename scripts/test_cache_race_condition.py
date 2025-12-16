"""
Test to demonstrate race condition in _content_length_cache that can cause
the cache to exceed its maximum size limit.
"""

import asyncio
import sys
from unittest.mock import Mock

# Add src to path
sys.path.insert(0, "src")

from src.core.config.app_config import AppConfig
from src.core.services.buffered_wire_capture_service import BufferedWireCapture


async def test_cache_race_condition():
    """Test that concurrent cache operations can exceed the limit."""
    config = Mock(spec=AppConfig)
    config.logging = Mock()
    config.logging.capture_file = None
    
    service = BufferedWireCapture(config)
    service._cache_max_size = 100  # Lower limit for testing
    
    # Fill cache to limit
    for i in range(100):
        payload = {"test": f"data_{i}"}
        service._get_content_length_cached(payload)
    
    print(f"Cache size after filling: {len(service._content_length_cache)}")
    assert len(service._content_length_cache) == 100
    
    # Now create many concurrent operations that will all try to add entries
    async def add_entry(index):
        payload = {"concurrent": f"data_{index}"}
        service._get_content_length_cached(payload)
    
    # Create 50 concurrent operations
    tasks = [add_entry(i) for i in range(50)]
    await asyncio.gather(*tasks)
    
    final_size = len(service._content_length_cache)
    print(f"Cache size after concurrent operations: {final_size}")
    
    if final_size > service._cache_max_size:
        print(f"❌ RACE CONDITION CONFIRMED: Cache exceeded limit!")
        print(f"   Limit: {service._cache_max_size}, Actual: {final_size}")
        return True
    else:
        print("✅ Cache stayed within limit")
        return False
    
    await service.shutdown()


if __name__ == "__main__":
    leak_found = asyncio.run(test_cache_race_condition())
    sys.exit(1 if leak_found else 0)
