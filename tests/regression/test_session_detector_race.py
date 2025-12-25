"""
Regression test for race condition in SessionDetector.

Tests that cache invalidation methods properly use locks.
"""
import pytest
import asyncio
from src.connectors._openai_codex_session_detector import SessionDetector


@pytest.mark.asyncio
async def test_cache_invalidation_concurrent_access():
    """
    Test that cache invalidation methods are thread-safe.
    
    Previously, invalidate_cache_for_backend_change and 
    invalidate_cache_for_agent_change accessed _cache without locks,
    causing potential race conditions.
    """
    detector = SessionDetector(cache_ttl_seconds=10, max_cache_size=100)
    
    # Populate cache
    for i in range(50):
        cache_key = SessionDetector._build_cache_key(f"session_{i}", "backend_1", "agent_1")
        async with detector._cache_lock:
            detector._cache[cache_key] = detector._cache.__class__.__dict__
    
    assert len(detector._cache) == 50
    
    # Simulate concurrent cache invalidation and access
    async def concurrent_access():
        for i in range(20):
            cache_key = SessionDetector._build_cache_key(f"session_{i}", "backend_1", "agent_1")
            async with detector._cache_lock:
                detector._cache.get(cache_key)
                detector._cache_hits += 1
    
    tasks = [asyncio.create_task(concurrent_access()) for _ in range(5)]
    tasks.append(asyncio.create_task(detector.invalidate_cache_for_backend_change("backend_1", "backend_2")))
    
    # Should complete without errors
    await asyncio.gather(*tasks, return_exceptions=True)
    
    # Cache should be cleared
    assert len(detector._cache) == 0


@pytest.mark.asyncio
async def test_concurrent_invalidations():
    """
    Test that multiple concurrent invalidations don't cause errors.
    """
    detector = SessionDetector(cache_ttl_seconds=10, max_cache_size=100)
    
    # Populate cache
    for i in range(50):
        cache_key = SessionDetector._build_cache_key(f"session_{i}", "backend_1", "agent_1")
        async with detector._cache_lock:
            detector._cache[cache_key] = None
    
    assert len(detector._cache) == 50
    
    # Run concurrent invalidations
    task1 = asyncio.create_task(detector.invalidate_cache_for_backend_change("backend_1", "backend_2"))
    task2 = asyncio.create_task(detector.invalidate_cache_for_agent_change("agent_1", "agent_2"))
    task3 = asyncio.create_task(detector.invalidate_cache_for_backend_change("backend_1", "backend_3"))
    
    # Should complete without errors
    await asyncio.gather(task1, task2, task3)
    
    # Cache should be cleared
    assert len(detector._cache) == 0


@pytest.mark.asyncio
async def test_cache_stats_consistency():
    """
    Test that cache stats remain consistent under concurrent access.
    """
    detector = SessionDetector(cache_ttl_seconds=10, max_cache_size=100)
    
    # Populate some cache entries
    for i in range(30):
        cache_key = detector._build_cache_key(f"session_{i}", "backend_1", "agent_1")
        async with detector._cache_lock:
            detector._cache[cache_key] = None
    
    # Simulate concurrent operations
    async def worker(worker_id: int):
        for i in range(20):
            cache_key = SessionDetector._build_cache_key(f"session_{i}", "backend_1", "agent_1")
            async with detector._cache_lock:
                if cache_key in detector._cache:
                    detector._cache_hits += 1
                else:
                    detector._cache_misses += 1
    
    tasks = [asyncio.create_task(worker(i)) for i in range(10)]
    await asyncio.gather(*tasks)
    
    # Stats should be consistent
    stats = detector.get_cache_stats()
    assert stats.total_entries == len(detector._cache)
    assert stats.hits + stats.misses == detector._cache_hits + detector._cache_misses
    assert stats.hit_rate == stats.hits / (stats.hits + stats.misses) if (stats.hits + stats.misses) > 0 else 0.0
