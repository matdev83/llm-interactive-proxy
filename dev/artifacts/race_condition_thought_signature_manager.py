"""
Repro script for race condition in ThoughtSignatureManager.

The ThoughtSignatureManager modifies shared dictionaries (self._cache,
self._by_tool_call) without any lock protection.
"""

import asyncio
import threading
import time
from collections import OrderedDict


class ThoughtSignatureManager:
    """Simplified version with race condition."""

    def __init__(self, max_cache_size: int = 10000):
        self._max_cache_size = max_cache_size
        self._cache: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._by_tool_call: dict[str, str] = {}  # Secondary index

    def store_signatures_from_tool_calls(
        self,
        tool_calls: list[dict[str, str]],
        session_id: str | None,
    ) -> None:
        """Store signatures - NO LOCK PROTECTION"""
        current_time = time.time()

        for tc in tool_calls:
            tc_id = tc.get("id", "")
            sig = tc.get("signature")
            if not sig or not tc_id:
                continue

            cache_key = f"{session_id}:{tc_id}" if session_id else f"anon:{tc_id}"
            self._cache[cache_key] = (sig, current_time)
            self._by_tool_call[tc_id] = sig  # RACE: Concurrent writes
            self._cache.move_to_end(cache_key)

            # Enforce size limit
            if len(self._cache) > self._max_cache_size:
                self._evict_oldest()  # RACE: Modifies both dicts

    def inject_signatures(self, tool_calls: list[dict], session_id: str) -> list[dict]:
        """Inject signatures - NO LOCK PROTECTION"""
        results = []
        current_time = time.time()

        for tc in tool_calls:
            tc_id = tc.get("id")
            if not tc_id:
                continue

            # RACE: Concurrent reads while other thread modifies
            cache_key = f"{session_id}:{tc_id}"
            cache_entry = self._cache.get(cache_key)
            sig = None

            if cache_entry:
                cached_sig, timestamp = cache_entry
                if current_time - timestamp > 3600:  # 1 hour TTL
                    # RACE: Delete while iterating
                    del self._cache[cache_key]
                    self._by_tool_call.pop(tc_id, None)  # RACE: Concurrent delete
                else:
                    sig = cached_sig

            if sig:
                tc["injected_signature"] = sig
            results.append(tc)

        return results

    def _evict_oldest(self) -> None:
        """Evict oldest entry - NO LOCK PROTECTION"""
        oldest_key, _ = self._cache.popitem(last=False)
        # RACE: This rebuild is not atomic
        new_by_tool_call = {}
        for cache_key, (sig, _) in self._cache.items():
            tc_id = cache_key.split(":", 1)[1] if ":" in cache_key else cache_key
            new_by_tool_call[tc_id] = sig
        self._by_tool_call = new_by_tool_call


def sync_race_test():
    """Test race condition with threads."""
    print("\n=== Testing with threads ===")
    manager = ThoughtSignatureManager(max_cache_size=10)
    errors = []
    results = []

    def worker(worker_id: int):
        try:
            for i in range(10):
                tool_calls = [
                    {"id": f"tc_{worker_id}_{i}", "signature": f"sig_{worker_id}_{i}"}
                ]
                manager.store_signatures_from_tool_calls(
                    tool_calls, f"session_{worker_id}"
                )

                # Concurrent access
                tool_calls_to_inject = [{"id": f"tc_{worker_id}_{i}"}]
                manager.inject_signatures(tool_calls_to_inject, f"session_{worker_id}")

        except Exception as e:
            errors.append((worker_id, str(e)))

    # Create many threads
    threads = []
    for i in range(10):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    if errors:
        print(f"Threaded test: {len(errors)} errors detected")
        return True
    else:
        print("Threaded test: No errors (but race condition exists)")
        return False


async def async_race_test():
    """Test race condition with asyncio."""
    print("\n=== Testing with asyncio ===")
    manager = ThoughtSignatureManager(max_cache_size=10)
    errors = []

    async def worker(worker_id: int):
        try:
            for i in range(10):
                tool_calls = [
                    {"id": f"tc_{worker_id}_{i}", "signature": f"sig_{worker_id}_{i}"}
                ]
                manager.store_signatures_from_tool_calls(
                    tool_calls, f"session_{worker_id}"
                )

                # Small delay to increase race window
                await asyncio.sleep(0.0001)

                tool_calls_to_inject = [{"id": f"tc_{worker_id}_{i}"}]
                manager.inject_signatures(tool_calls_to_inject, f"session_{worker_id}")

        except Exception as e:
            errors.append((worker_id, str(e)))

    tasks = [worker(i) for i in range(10)]
    await asyncio.gather(*tasks, return_exceptions=True)

    if errors:
        print(f"Async test: {len(errors)} errors detected")
        return True
    else:
        print("Async test: No errors (but race condition exists)")
        return False


async def main():
    print("Running race condition test for ThoughtSignatureManager...")
    print("-" * 60)

    # Run thread test
    thread_race = sync_race_test()

    # Run async test
    async_race = await async_race_test()

    print("-" * 60)
    if thread_race or async_race:
        print("RESULT: Race condition CONFIRMED")
    else:
        print("RESULT: Race condition exists but errors are non-deterministic")
    print("\nFix: Add threading.Lock() or asyncio.Lock() to protect cache access")


if __name__ == "__main__":
    asyncio.run(main())
