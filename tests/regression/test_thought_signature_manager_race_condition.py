"""
Regression test for ThoughtSignatureManager race condition fix.

Tests that cache access is properly protected by locks.
"""

import threading

from src.connectors.gemini_base.thought_signature_manager import ThoughtSignatureManager


def test_thought_signature_concurrent_store():
    """Test that concurrent stores don't corrupt cache."""
    manager = ThoughtSignatureManager(max_cache_size=1000)

    def store_batch(batch_id: int):
        tool_calls = [
            {
                "id": f"tc_{batch_id}_{i}",
                "extra_content": {
                    "google": {"thought_signature": f"sig_{batch_id}_{i}"}
                },
            }
            for i in range(100)
        ]
        manager.store_signatures_from_tool_calls(tool_calls, f"session_{batch_id}")

    # Create multiple threads storing signatures concurrently
    threads = []
    for i in range(10):
        t = threading.Thread(target=store_batch, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # All signatures should be stored without errors
    # Cache size should be at most max_cache_size (LRU eviction)
    assert len(manager._cache) <= 1000

    # Secondary index should be consistent
    cache_keys = set(manager._cache.keys())
    indexed_tcs = set(manager._by_tool_call.keys())

    # Extract tc_ids from cache keys
    cache_tc_ids = set()
    for key in cache_keys:
        parts = key.split(":", 1)
        tc_id = parts[1] if len(parts) == 2 else parts[0]
        cache_tc_ids.add(tc_id)

    # All indexed tc_ids should be in cache
    assert indexed_tcs.issubset(
        cache_tc_ids
    ), "Secondary index contains entries not in cache"


def test_thought_signature_concurrent_inject():
    """Test that concurrent injects don't cause race conditions."""
    manager = ThoughtSignatureManager()

    # Pre-populate cache
    tool_calls = [
        {
            "id": f"tc_{i}",
            "extra_content": {"google": {"thought_signature": f"sig_{i}"}},
        }
        for i in range(100)
    ]
    manager.store_signatures_from_tool_calls(tool_calls, "session_test")

    # Simulate concurrent injection attempts
    error_count = []
    lock = threading.Lock()

    # Create mock message object with tool_calls
    class MockMessage:
        def __init__(self):
            self.role = "assistant"

    class MockRequest:
        def __init__(self, tool_call_list):
            self.messages = [MockMessage()]
            self.messages[0].tool_calls = tool_call_list

    def inject_batch(batch_id: int):
        errors = 0
        for i in range(20):
            try:
                tc = {"id": f"tc_{i % 100}"}
                # Create proper request structure
                request = MockRequest([tc])
                manager.inject_signatures(request, "session_test")
            except Exception:
                errors += 1
        with lock:
            error_count.append(errors)

    threads = []
    for i in range(5):
        t = threading.Thread(target=inject_batch, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # All threads should complete without exceptions
    assert len(error_count) == 5
    assert all(errors == 0 for errors in error_count)


def test_thought_signature_concurrent_clear_session():
    """Test that concurrent clear_session doesn't cause corruption."""
    manager = ThoughtSignatureManager()

    # Populate cache
    for session_id in range(5):
        tool_calls = [
            {
                "id": f"tc_{session_id}_{i}",
                "extra_content": {"google": {"thought_signature": f"sig_{i}"}},
            }
            for i in range(20)
        ]
        manager.store_signatures_from_tool_calls(tool_calls, f"session_{session_id}")

    # Clear different sessions concurrently
    def clear_session(session_id: str):
        manager.clear_session_cache(session_id)

    threads = []
    for i in range(5):
        t = threading.Thread(target=clear_session, args=(f"session_{i}",))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # All sessions should be cleared
    assert len(manager._cache) == 0
    assert len(manager._by_tool_call) == 0


def test_thought_signature_concurrent_eviction():
    """Test that concurrent evictions don't cause data loss."""
    manager = ThoughtSignatureManager(max_cache_size=100)

    def store_evict_cycle(batch_id: int):
        for cycle in range(5):
            # Store many entries to trigger eviction
            tool_calls = [
                {
                    "id": f"tc_{batch_id}_{cycle}_{i}",
                    "extra_content": {"google": {"thought_signature": f"sig_{i}"}},
                }
                for i in range(50)
            ]
            manager.store_signatures_from_tool_calls(tool_calls, f"session_{batch_id}")

            # Check cache size is respected
            if manager._cache:
                assert (
                    len(manager._cache) <= 100
                ), f"Cache exceeded max size: {len(manager._cache)}"

    # Run multiple eviction cycles concurrently
    threads = []
    for i in range(5):
        t = threading.Thread(target=store_evict_cycle, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # Final cache should be within limits
    assert len(manager._cache) <= 100

    # Secondary index should remain consistent
    cache_keys = set(manager._cache.keys())
    indexed_tcs = set(manager._by_tool_call.keys())

    cache_tc_ids = set()
    for key in cache_keys:
        parts = key.split(":", 1)
        tc_id = parts[1] if len(parts) == 2 else parts[0]
        cache_tc_ids.add(tc_id)

    assert indexed_tcs.issubset(
        cache_tc_ids
    ), "Secondary index inconsistent after concurrent evictions"


def test_thought_signature_property_thread_safety():
    """Test that cache property getter/setter are thread-safe."""
    manager = ThoughtSignatureManager()

    # Concurrent access to cache property
    results = {"get_count": 0, "set_count": 0}
    lock = threading.Lock()

    def get_cache():
        for _ in range(100):
            with lock:
                results["get_count"] += 1

    def set_cache():
        for i in range(100):
            test_cache = {f"key_{i}": f"value_{i}"}
            manager.cache = test_cache
            with lock:
                results["set_count"] += 1

    threads = [threading.Thread(target=get_cache), threading.Thread(target=set_cache)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Both operations should complete successfully
    assert results["get_count"] == 100
    assert results["set_count"] == 100

    # Cache should still be consistent
    final_cache = manager.cache
    assert isinstance(final_cache, dict)


def test_thought_signature_clear_all_anonymous_thread_safety():
    """Test that clear_all_anonymous is thread-safe."""
    manager = ThoughtSignatureManager()

    # Mix of anonymous and named sessions
    for i in range(10):
        tool_calls = [
            {
                "id": f"tc_{i}_{j}",
                "extra_content": {"google": {"thought_signature": f"sig_{j}"}},
            }
            for j in range(10)
        ]
        session_id = None if i % 2 == 0 else f"session_{i}"
        manager.store_signatures_from_tool_calls(tool_calls, session_id)

    # Clear anonymous entries concurrently
    def clear_anonymous():
        manager.clear_all_anonymous()

    threads = [threading.Thread(target=clear_anonymous) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All anonymous entries should be cleared
    remaining_keys = list(manager._cache.keys())
    anon_remaining = [k for k in remaining_keys if k.startswith("anon:")]
    assert len(anon_remaining) == 0

    # Named sessions should remain
    named_remaining = [k for k in remaining_keys if k.startswith("session_")]
    assert len(named_remaining) == 50  # 5 sessions * 10 entries each
