"""Regression test for MemoryService cleanup tasks being GC'd before completion.

This test verifies that MemoryService cleanup tasks are not garbage collected
before they complete, preventing resource leaks (HTTP connections, file handles, etc.).
"""

import asyncio
import gc

import pytest
from src.core.memory.config import MemoryConfiguration
from src.core.memory.service import MemoryService


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

        # Verify _cleanup_tasks is a set (not WeakSet) to prevent GC before completion

        assert isinstance(
            memory_service._cleanup_tasks, set
        ), f"Expected set to prevent GC before completion, got {type(memory_service._cleanup_tasks)}"

        # Enable a session
        session_id = "test_session_leak"
        await memory_service.enable_for_session(
            session_id,
            user_id="test-user",
            project_root="/project/test",
        )

        # Create cleanup tasks that take some time to complete
        async def slow_cleanup():
            await asyncio.sleep(0.1)  # Simulate cleanup work
            return "done"

        async with memory_service._state_lock:
            cleanup_task1 = asyncio.create_task(slow_cleanup())
            cleanup_task2 = asyncio.create_task(slow_cleanup())

            # Add to set (not WeakSet)
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

            # Tasks should still be tracked (because we use set, not WeakSet)
            remaining_count = len(memory_service._cleanup_tasks)
            assert remaining_count == 2, (
                f"Tasks were GC'd before completion! "
                f"Expected 2, got {remaining_count}. "
                f"This would cause resource leaks."
            )

        # Wait for tasks to complete
        await asyncio.sleep(0.2)

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
        for i in range(50):
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
                memory_service._cleanup_tasks.add(cleanup_task1)
                memory_service._cleanup_tasks.add(cleanup_task2)
                # Don't keep references - but tasks should still be tracked

            # Force GC periodically
            if i % 10 == 0:
                gc.collect()

        # Check how many tasks remain (should be all of them, not GC'd)
        remaining = len(memory_service._cleanup_tasks)
        expected_min = 50 * 2 - 20  # At least 80 tasks (allowing for some completion)
        assert remaining >= expected_min, (
            f"Many tasks were GC'd before completion! "
            f"Expected at least {expected_min}, got {remaining}. "
            f"This would cause resource leaks."
        )

        # Cleanup should await all tasks
        await memory_service.cleanup()
        assert len(memory_service._cleanup_tasks) == 0, "All tasks should be cleaned up"
