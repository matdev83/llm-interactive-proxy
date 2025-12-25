"""
Repro script for race condition in _openai_codex_session_detector.py

The `invalidate_cache_for_backend_change` and `invalidate_cache_for_agent_change` 
methods access and clear `_cache` WITHOUT acquiring `_cache_lock`, causing race 
conditions when concurrent operations are in progress.
"""
import asyncio
from src.connectors._openai_codex_session_detector import SessionDetector


async def test_cache_invalidation_race():
    """
    Simulate concurrent cache invalidation and access operations.
    This should expose the race condition.
    """
    detector = SessionDetector(cache_ttl_seconds=10, max_cache_size=100)
    
    # Populate cache with some entries
    for i in range(50):
        cache_key = detector._build_cache_key(f"session_{i}", "backend_1", "agent_1")
        detector._cache[cache_key] = detector._cache.__class__.__dict__
        if i % 10 == 0:
            print(f"Populated {i} entries...")
    
    print(f"Cache populated with {len(detector._cache)} entries")
    
    # Now simulate concurrent operations
    tasks = []
    
    async def concurrent_cache_access():
        """Simulate normal cache access"""
        for i in range(20):
            cache_key = detector._build_cache_key(f"session_{i}", "backend_1", "agent_1")
            async with detector._cache_lock:
                result = detector._cache.get(cache_key)
                if result:
                    detector._cache_hits += 1
    
    async def concurrent_invalidate():
        """Simulate cache invalidation"""
        await asyncio.sleep(0.001)
        detector.invalidate_cache_for_backend_change("backend_1", "backend_2")
    
    # Create many concurrent tasks
    for _ in range(5):
        tasks.append(asyncio.create_task(concurrent_cache_access()))
    tasks.append(asyncio.create_task(concurrent_invalidate()))
    
    # Run all tasks concurrently
    await asyncio.gather(*tasks, return_exceptions=True)
    
    print(f"Final cache size: {len(detector._cache)}")
    print(f"Cache hits: {detector._cache_hits}, Cache misses: {detector._cache_misses}")
    
    # Check for inconsistent state
    stats = detector.get_cache_stats()
    print(f"Cache stats: total={stats.total_entries}, hits={stats.hits}, misses={stats.misses}")
    print("Test completed - no exception raised but race condition exists!")


async def test_double_clear_issue():
    """
    Test concurrent invalidation calls causing double-clear.
    """
    detector = SessionDetector(cache_ttl_seconds=10, max_cache_size=100)
    
    # Populate cache
    for i in range(50):
        cache_key = detector._build_cache_key(f"session_{i}", "backend_1", "agent_1")
        detector._cache[cache_key] = None
    
    print(f"Cache populated with {len(detector._cache)} entries")
    
    # Simulate concurrent invalidation
    task1 = asyncio.create_task(detector.invalidate_cache_for_backend_change("backend_1", "backend_2"))
    task2 = asyncio.create_task(detector.invalidate_cache_for_agent_change("agent_1", "agent_2"))
    task3 = asyncio.create_task(detector.invalidate_cache_for_backend_change("backend_1", "backend_3"))
    
    await asyncio.gather(task1, task2, task3)
    
    print(f"Final cache size: {len(detector._cache)} (should be 0)")
    print("Test completed")


if __name__ == "__main__":
    print("=== Testing Session Detector Race Condition ===")
    asyncio.run(test_cache_invalidation_race())
    print()
    asyncio.run(test_double_clear_issue())
