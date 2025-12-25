"""Regression test for ConcurrencyGuard thread safety.

This test verifies that ConcurrencyGuard's operation counting
is thread-safe under concurrent access.
"""

import asyncio

import pytest_asyncio
from src.core.services.production_concurrency_guard import (
    ConcurrencyGuard,
)


class TestConcurrencyGuardThreadSafety:
    """Test suite for ConcurrencyGuard thread safety."""

    @pytest_asyncio.fixture(autouse=True)
    def set_event_loop_policy(self):
        policy = asyncio.WindowsSelectorEventLoopPolicy()
        asyncio.set_event_loop_policy(policy)

    async def test_concurrent_acquire_queuing(self):
        """Test that concurrent acquires are queued and processed."""
        guard = ConcurrencyGuard(max_concurrent=2, name="test-guard")

        success_count = 0
        reject_count = 0
        completed_count = 0

        async def try_acquire(i):
            nonlocal success_count, reject_count, completed_count
            try:
                async with guard.acquire(f"operation_{i}"):
                    success_count += 1
                    await asyncio.sleep(0.01)
            except Exception as e:
                if "limit reached" in str(e):
                    reject_count += 1
                else:
                    raise
            finally:
                completed_count += 1

        # Launch 10 concurrent operations (limit is 2, should all succeed eventually)
        tasks = [try_acquire(i) for i in range(10)]
        await asyncio.gather(*tasks, return_exceptions=True)

        print(
            f"Success: {success_count}, Rejected: {reject_count}, Total: {guard._total_operations}"
        )

        # With queuing, all should succeed
        assert (
            success_count == 10
        ), f"Expected 10 successful acquires, got {success_count}"
        assert reject_count == 0, f"Expected 0 rejected acquires, got {reject_count}"
        assert (
            guard._total_operations == 10
        ), f"Expected 10 total operations tracked, got {guard._total_operations}"
        assert (
            guard._rejected_operations == 0
        ), f"Expected 0 rejected operations, got {guard._rejected_operations}"
        assert completed_count == 10, f"Expected 10 completions, got {completed_count}"

    async def test_active_operations_accounting(self):
        """Test that active operations are properly tracked."""
        guard = ConcurrencyGuard(max_concurrent=3, name="test-guard")

        async def operation(i):
            async with guard.acquire(f"op_{i}"):
                await asyncio.sleep(0.01)
                # Verify operation is in active set
                assert (
                    len([x for x in guard._active_operations if f"op_{i}" in str(x)])
                    <= 1
                ), f"Duplicate operation IDs found for op_{i}"

        # Run 5 operations with limit of 3
        tasks = [operation(i) for i in range(5)]
        await asyncio.gather(*tasks)

        assert (
            guard._total_operations == 5
        ), f"Expected 5 total operations, got {guard._total_operations}"
        assert (
            guard._rejected_operations == 0
        ), f"Expected 0 rejected, got {guard._rejected_operations}"

    async def test_concurrent_operations_cleanup(self):
        """Test that operations are cleaned up after completion."""
        guard = ConcurrencyGuard(max_concurrent=5, name="test-guard")

        # Run operations sequentially
        for i in range(3):
            async with guard.acquire(f"op_{i}"):
                await asyncio.sleep(0.01)

        # All operations should be cleaned up
        assert (
            len(list(guard._active_operations)) == 0
        ), f"Expected 0 active operations, got {len(list(guard._active_operations))}"
        assert guard._total_operations == 3
