"""Regression test for MemoryService cleanup tasks leak fix.

This test verifies that MemoryService.cleanup() is called during shutdown
to ensure cleanup tasks are properly awaited.
"""

import asyncio

import pytest
from src.core.memory.config import MemoryConfiguration
from src.core.memory.service import MemoryService


class MockRepository:
    """Mock repository for testing."""

    async def get_or_create_project_id(self, user_id: str, project_root: str) -> str:
        return "mock-project-id"


@pytest.mark.asyncio
async def test_cleanup_awaits_pending_tasks():
    """Test that cleanup() awaits pending cleanup tasks."""
    config = MemoryConfiguration(available=True, max_buffer_size_bytes=1024 * 1024)
    repository = MockRepository()
    memory_service = MemoryService(config, repository)

    # Verify _cleanup_tasks is a set (not WeakSet)
    assert isinstance(
        memory_service._cleanup_tasks, set
    ), "Expected set, got {type(memory_service._cleanup_tasks)}"

    # Enable a session
    session_id = "test_session"
    await memory_service.enable_for_session(
        session_id,
        user_id="test-user",
        project_root="/project/test",
    )

    # Create cleanup tasks (simulating what happens during eviction)
    async with memory_service._state_lock:
        cleanup_task1 = memory_service._capture_buffer.clear_session(session_id)
        cleanup_task2 = memory_service._tool_event_collector.clear_session(session_id)

        task1 = asyncio.create_task(cleanup_task1)
        task2 = asyncio.create_task(cleanup_task2)

        memory_service._cleanup_tasks.add(task1)
        memory_service._cleanup_tasks.add(task2)

    # Verify tasks are tracked
    assert len(memory_service._cleanup_tasks) == 2

    # Call cleanup()
    await memory_service.cleanup()

    # Verify tasks were awaited and cleared
    assert len(memory_service._cleanup_tasks) == 0
    assert task1.done()
    assert task2.done()


@pytest.mark.asyncio
async def test_cleanup_handles_timeout():
    """Test that cleanup() handles timeout correctly."""
    config = MemoryConfiguration(available=True, max_buffer_size_bytes=1024 * 1024)
    repository = MockRepository()
    memory_service = MemoryService(config, repository)

    # Create a task that takes longer than timeout
    async def slow_task():
        await asyncio.sleep(10)  # Longer than 5s timeout

    task = asyncio.create_task(slow_task())
    memory_service._cleanup_tasks.add(task)

    # Call cleanup() - should timeout and cancel task
    await memory_service.cleanup()

    # Verify task was cancelled
    assert task.cancelled()
    assert len(memory_service._cleanup_tasks) == 0


@pytest.mark.asyncio
async def test_cleanup_idempotent():
    """Test that cleanup() can be called multiple times safely."""
    config = MemoryConfiguration(available=True, max_buffer_size_bytes=1024 * 1024)
    repository = MockRepository()
    memory_service = MemoryService(config, repository)

    session_id = "test_session"
    await memory_service.enable_for_session(
        session_id,
        user_id="test-user",
        project_root="/project/test",
    )

    # Create cleanup tasks
    async with memory_service._state_lock:
        cleanup_task1 = memory_service._capture_buffer.clear_session(session_id)
        task1 = asyncio.create_task(cleanup_task1)
        memory_service._cleanup_tasks.add(task1)

    # Call cleanup() multiple times
    await memory_service.cleanup()
    await memory_service.cleanup()
    await memory_service.cleanup()

    # Should not raise exception and should be idempotent
    assert len(memory_service._cleanup_tasks) == 0
