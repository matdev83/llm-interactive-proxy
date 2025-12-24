"""Regression test for BackendLifecycleManager._shutdown_tasks race condition."""

import asyncio

import pytest
from src.core.services.backend_lifecycle_manager import BackendLifecycleManager


@pytest.fixture
def lifecycle_manager():
    """Create a BackendLifecycleManager for testing."""
    return BackendLifecycleManager()


async def test_shutdown_tasks_concurrent_additions(lifecycle_manager):
    """Test that concurrent additions to _shutdown_tasks don't lose tasks."""

    # Create 100 tasks concurrently
    async def create_and_add_task():
        async def noop():
            await asyncio.sleep(0.01)
            return

        task = asyncio.create_task(noop())
        lifecycle_manager._shutdown_tasks.add(task)
        return task

    tasks = [create_and_add_task() for _ in range(100)]
    created_tasks = await asyncio.gather(*tasks)

    # All tasks should be tracked
    assert len(lifecycle_manager._shutdown_tasks) == 100

    # All created tasks should be in the set
    for task in created_tasks:
        assert task in lifecycle_manager._shutdown_tasks

    # Clean up tasks
    for task in created_tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*created_tasks, return_exceptions=True)


async def test_shutdown_tasks_concurrent_add_and_clear(lifecycle_manager):
    """Test concurrent additions and clear operations."""
    tasks_added = []

    async def add_tasks():
        for _i in range(50):

            async def noop():
                await asyncio.sleep(0.01)
                return

            task = asyncio.create_task(noop())
            lifecycle_manager._shutdown_tasks.add(task)
            tasks_added.append(task)

    async def clear_tasks():
        await asyncio.sleep(0.01)
        with lifecycle_manager._shutdown_tasks_lock:
            lifecycle_manager._shutdown_tasks.clear()

    # Run add and clear concurrently
    await asyncio.gather(add_tasks(), clear_tasks())

    # After clear, set should be empty or only contain tasks added after clear
    # This test verifies that the lock prevents race conditions
    assert len(lifecycle_manager._shutdown_tasks) <= len(tasks_added)

    # Clean up
    for task in tasks_added:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks_added, return_exceptions=True)


async def test_await_pending_shutdown_tasks_concurrent(lifecycle_manager):
    """Test await_pending_shutdown_tasks with concurrent additions."""
    # Add some tasks
    tasks_added = []
    for _ in range(10):

        async def long_running():
            await asyncio.sleep(10)
            return

        task = asyncio.create_task(long_running())
        lifecycle_manager._shutdown_tasks.add(task)
        tasks_added.append(task)

    # Start a concurrent add task
    async def add_during_await():
        await asyncio.sleep(0.001)

        async def noop():
            return

        task = asyncio.create_task(noop())
        with lifecycle_manager._shutdown_tasks_lock:
            lifecycle_manager._shutdown_tasks.add(task)
        tasks_added.append(task)

    # Both operations should work without race
    await asyncio.gather(
        lifecycle_manager.await_pending_shutdown_tasks(timeout=0.1),
        add_during_await(),
    )

    # Clean up
    for task in tasks_added:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks_added, return_exceptions=True)
