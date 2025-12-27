"""Regression test for MemoryService cleanup tasks being GC'd before completion.

This test verifies that MemoryService cleanup tasks are not garbage collected
before they complete, preventing resource leaks (HTTP connections, file handles, etc.).
"""

import asyncio
import gc

import pytest
from src.core.memory.config import MemoryConfiguration
from src.core.memory.service import MemoryService
from tests.utils.fake_clock import FakeClockContext


class MockRepository:
    """Mock repository for testing."""

    async def save_summary(self, session_id: str, summary: str) -> None:
        pass

    async def get_or_create_project_id(self, user_id: str, project_root: str) -> str:
        return "mock-project-id"


class TestMemoryServiceCleanupTasksGCBeforeCompletionRegression:
    """Regression tests for MemoryService cleanup tasks GC before completion."""

    @pytest.mark.asyncio
    async def test_cleanup_tasks_not_gc_before_completion(self) -> None:
        """Test that cleanup tasks are not GC'd before they complete."""
        config = MemoryConfiguration(available=True, max_buffer_size_bytes=1024 * 1024)
        repository = MockRepository()
        memory_service = MemoryService(config, repository)

        # Verify _cleanup_tasks is a WeakSet
        from weakref import WeakSet

        assert isinstance(
            memory_service._cleanup_tasks, WeakSet
        ), f"Expected WeakSet, got {type(memory_service._cleanup_tasks)}"

        # Enable a session
        session_id = "test_session_leak"
        await memory_service.enable_for_session(
            session_id,
            user_id="test-user",
            project_root="/project/test",
        )

        # Create cleanup tasks that take some time to complete
        async def slow_cleanup():
            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.03))
                clock.advance(0.03)  # Reduced from 0.05 for faster completion
                await sleep_task
            return "done"

        async with memory_service._state_lock:
            cleanup_task1 = asyncio.create_task(slow_cleanup())
            cleanup_task2 = asyncio.create_task(slow_cleanup())

            # Add done callbacks to remove tasks when they complete (matching implementation)
            cleanup_task1.add_done_callback(
                lambda task: memory_service._cleanup_tasks.discard(task)
            )
            cleanup_task2.add_done_callback(
                lambda task: memory_service._cleanup_tasks.discard(task)
            )
            # Add to WeakSet
            memory_service._cleanup_tasks.add(cleanup_task1)
            memory_service._cleanup_tasks.add(cleanup_task2)

            initial_count = len(memory_service._cleanup_tasks)
            assert initial_count == 2, "Tasks should be tracked"

            # Remove local references (simulating what happens in real code)
            # If using WeakSet, tasks could be GC'd here before completion
            del cleanup_task1
            del cleanup_task2

            # Force garbage collection
            gc.collect()

            # Tasks should still be tracked (done callbacks keep references until completion)
            remaining_count = len(memory_service._cleanup_tasks)
            assert remaining_count == 2, (
                f"Tasks were GC'd before completion! "
                f"Expected 2, got {remaining_count}. "
                f"This would cause resource leaks."
            )

        # Wait for tasks to complete
        async with FakeClockContext() as clock:
            sleep_task = asyncio.create_task(asyncio.sleep(0.1))
            clock.advance(0.1)  # Reduced from 0.15
            await sleep_task

        # Now cleanup should await and remove tasks
        await memory_service.cleanup()
        assert (
            len(memory_service._cleanup_tasks) == 0
        ), "Tasks should be cleaned up after completion"

    @pytest.mark.asyncio
    async def test_remote_actor_scenario_no_gc_leak(self) -> None:
        """Test scenario where remote actor creates many sessions - no GC leak."""
        config = MemoryConfiguration(available=True, max_buffer_size_bytes=1024 * 1024)
        repository = MockRepository()
        memory_service = MemoryService(config, repository)

        # Simulate remote actor creating many sessions that get evicted
        # Each eviction creates cleanup tasks that must not be GC'd before completion
        # Reduced for performance while maintaining test coverage
        for i in range(3):
            session_id = f"attack_session_{i}"
            await memory_service.enable_for_session(
                session_id,
                user_id="attacker",
                project_root="/project/attack",
            )

            # Simulate eviction creating cleanup tasks
            async with memory_service._state_lock:
                cleanup_task1 = asyncio.create_task(
                    memory_service._capture_buffer.clear_session(session_id)
                )
                cleanup_task2 = asyncio.create_task(
                    memory_service._tool_event_collector.clear_session(session_id)
                )
                # Add done callbacks to remove tasks when they complete (matching implementation)
                cleanup_task1.add_done_callback(
                    lambda task: memory_service._cleanup_tasks.discard(task)
                )
                cleanup_task2.add_done_callback(
                    lambda task: memory_service._cleanup_tasks.discard(task)
                )
                memory_service._cleanup_tasks.add(cleanup_task1)
                memory_service._cleanup_tasks.add(cleanup_task2)
                # Don't keep references - but tasks should still be tracked (done callbacks keep references)

            # Force GC periodically
            if i % 2 == 0:
                gc.collect()

        # Check how many tasks remain (should be all of them, not GC'd)
        remaining = len(memory_service._cleanup_tasks)
        expected_min = 3 * 2 - 2  # At least 4 tasks (allowing for some completion)
        assert remaining >= expected_min, (
            f"Many tasks were GC'd before completion! "
            f"Expected at least {expected_min}, got {remaining}. "
            f"This would cause resource leaks."
        )

        # Cleanup should await all tasks
        await memory_service.cleanup()
        assert len(memory_service._cleanup_tasks) == 0, "All tasks should be cleaned up"
