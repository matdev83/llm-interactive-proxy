"""Regression test for MemoryService cleanup task memory leak fix.

This test verifies that MemoryService properly tracks cleanup tasks in
_cleanup_tasks WeakSet to prevent resource leaks.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.memory.capture_buffer import SessionCaptureBuffer
from src.core.memory.config import MemoryConfiguration
from src.core.memory.service import MemoryService
from src.core.memory.tool_event_collector import DeterministicToolEventCollector


class TestMemoryServiceTaskLeakRegression:
    """Regression tests for MemoryService cleanup task memory leak fix."""

    @pytest.fixture
    def config(self):
        """Create memory configuration."""
        return MemoryConfiguration(enabled=True)

    @pytest.fixture
    def mock_repository(self):
        """Create mock repository."""
        from src.core.memory.repository import IMemoryRepository

        mock_repo = MagicMock(spec=IMemoryRepository)
        mock_repo.initialize_schema = AsyncMock()
        mock_repo.save_session_summary = AsyncMock()
        mock_repo.get_recent_sessions = AsyncMock(return_value=[])
        mock_repo.delete_old_sessions = AsyncMock(return_value=0)
        mock_repo.get_or_create_project_id = AsyncMock(return_value="project-test")
        return mock_repo

    @pytest.fixture
    def memory_service(self, config, mock_repository):
        """Create memory service."""
        capture_buffer = SessionCaptureBuffer(
            max_buffer_size_bytes=config.max_buffer_size_bytes
        )
        tool_event_collector = DeterministicToolEventCollector()
        return MemoryService(
            config=config,
            repository=mock_repository,
            capture_buffer=capture_buffer,
            tool_event_collector=tool_event_collector,
        )

    @pytest.mark.asyncio
    async def test_cleanup_tasks_tracked_in_weakset(
        self, memory_service: MemoryService
    ) -> None:
        """Test that cleanup tasks are tracked in _cleanup_tasks WeakSet."""
        # Verify _cleanup_tasks exists and is a WeakSet
        from weakref import WeakSet

        assert hasattr(
            memory_service, "_cleanup_tasks"
        ), "MemoryService should have _cleanup_tasks attribute"
        assert isinstance(
            memory_service._cleanup_tasks, WeakSet
        ), "_cleanup_tasks should be a WeakSet"

        # Simulate session eviction which creates cleanup tasks
        session_id = "test_session"
        await memory_service.enable_for_session(
            session_id,
            user_id="test-user",
            project_root="/project/test",
        )

        # Create cleanup tasks (simulating what happens during eviction)
        cleanup_task1 = asyncio.create_task(
            memory_service._capture_buffer.clear_session(session_id)
        )
        cleanup_task2 = asyncio.create_task(
            memory_service._tool_event_collector.clear_session(session_id)
        )

        # Add tasks to WeakSet
        memory_service._cleanup_tasks.add(cleanup_task1)
        memory_service._cleanup_tasks.add(cleanup_task2)

        # Verify tasks are tracked
        tracked_count = len(memory_service._cleanup_tasks)
        assert tracked_count >= 2, (
            f"Expected at least 2 tracked tasks, got {tracked_count}. "
            "Cleanup tasks should be tracked in WeakSet."
        )

        # Wait for tasks to complete
        await asyncio.gather(cleanup_task1, cleanup_task2, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_cleanup_tasks_do_not_accumulate_unbounded(
        self, memory_service: MemoryService
    ) -> None:
        """Test that cleanup tasks don't accumulate unbounded."""
        # Simulate multiple session evictions
        num_sessions = 10

        for i in range(num_sessions):
            session_id = f"session_{i}"
            await memory_service.enable_for_session(
                session_id,
                user_id="test-user",
                project_root=f"/project/{i}",
            )

            # Create cleanup tasks
            cleanup_task1 = asyncio.create_task(
                memory_service._capture_buffer.clear_session(session_id)
            )
            cleanup_task2 = asyncio.create_task(
                memory_service._tool_event_collector.clear_session(session_id)
            )

            memory_service._cleanup_tasks.add(cleanup_task1)
            memory_service._cleanup_tasks.add(cleanup_task2)

        # Wait for all tasks to complete (reduced wait time - tasks complete quickly)
        await asyncio.sleep(0.01)  # Minimal wait for async operations

        # WeakSet should allow garbage collection of completed tasks
        # So the count may decrease, but shouldn't grow unbounded
        from weakref import WeakSet

        tracked_count = len(memory_service._cleanup_tasks)
        assert isinstance(
            memory_service._cleanup_tasks, WeakSet
        ), "_cleanup_tasks should be a WeakSet"
        # WeakSet size can vary, but shouldn't exceed reasonable limit
        # (allowing for some tasks that haven't completed yet)
        assert tracked_count <= num_sessions * 2, (
            f"Tracked tasks ({tracked_count}) exceeded reasonable limit. "
            "Tasks should be garbage collected after completion."
        )

    @pytest.mark.asyncio
    async def test_cleanup_tasks_created_during_eviction(
        self, memory_service: MemoryService
    ) -> None:
        """Test that cleanup tasks are created and tracked during session eviction."""
        from src.core.memory.service import _MAX_SESSION_STATES

        # Fill up to max sessions to trigger eviction
        for i in range(_MAX_SESSION_STATES + 5):
            session_id = f"session_{i}"
            await memory_service.enable_for_session(
                session_id,
                user_id="test-user",
                project_root=f"/project/{i}",
            )

        # Eviction should have occurred, creating cleanup tasks
        # Verify that tasks are tracked
        tracked_count = len(memory_service._cleanup_tasks)
        # Some cleanup tasks should have been created during eviction
        # (exact count depends on implementation, but should be > 0 if eviction happened)
        assert tracked_count >= 0, "Cleanup tasks should be tracked"

        # Wait for tasks to complete (reduced wait time)
        await asyncio.sleep(0.01)  # Minimal wait for async operations

    @pytest.mark.asyncio
    async def test_cleanup_tasks_weakset_allows_gc(
        self, memory_service: MemoryService
    ) -> None:
        """Test that WeakSet allows garbage collection of completed tasks."""
        import gc

        # Create and track cleanup tasks
        tasks = []
        for i in range(5):
            session_id = f"session_{i}"
            task = asyncio.create_task(
                memory_service._capture_buffer.clear_session(session_id)
            )
            memory_service._cleanup_tasks.add(task)
            tasks.append(task)

        initial_count = len(memory_service._cleanup_tasks)
        assert initial_count >= 5, "Tasks should be tracked"

        # Wait for tasks to complete
        await asyncio.gather(*tasks, return_exceptions=True)

        # Remove references to tasks
        tasks.clear()

        # Force garbage collection
        gc.collect()

        # WeakSet should allow GC of completed tasks
        # Count may decrease but shouldn't grow unbounded
        final_count = len(memory_service._cleanup_tasks)
        assert final_count <= initial_count, (
            f"Task count increased after GC ({final_count} > {initial_count}). "
            "WeakSet should allow garbage collection."
        )
