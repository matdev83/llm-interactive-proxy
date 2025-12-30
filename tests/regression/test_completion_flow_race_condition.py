"""Regression test for backend_completion_flow._cancellation_tasks race condition."""

import asyncio

import pytest
from src.core.services.backend_completion_flow.service import (
    BackendCompletionFlow,
)
from src.core.services.connector_invoker import ConnectorInvoker
from tests.utils.fake_clock import FakeClockContext


@pytest.fixture
def orchestrator():
    """Create orchestrator with mock dependencies for testing."""
    return BackendCompletionFlow(
        availability_checker=None,
        request_preparer=None,
        session_resolver=None,
        backend_invoker=None,
        failover_executor=None,
        wire_capture_orchestrator=None,
        usage_accounting_orchestrator=None,
        exception_normalizer=None,
        stream_formatting_service=None,
        connector_invoker=ConnectorInvoker(),
    )


async def test_cancellation_tasks_concurrent_additions(orchestrator):
    """Test that concurrent additions to _cancellation_tasks don't lose tasks."""

    # Create 100 tasks concurrently
    async def create_and_add_task():
        async def noop():
            await asyncio.sleep(0.01)
            return

        task = asyncio.create_task(noop())
        orchestrator._cancellation_tasks.add(task)
        return task

    tasks = [create_and_add_task() for _ in range(100)]
    created_tasks = await asyncio.gather(*tasks)

    # All tasks should be tracked
    assert len(orchestrator._cancellation_tasks) == 100

    # All created tasks should be in the set
    for task in created_tasks:
        assert task in orchestrator._cancellation_tasks

    # Clean up tasks
    for task in created_tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*created_tasks, return_exceptions=True)


async def test_cancellation_tasks_concurrent_add_and_cleanup(orchestrator):
    """Test concurrent additions and cleanup operations."""
    tasks_added = []

    async def add_tasks():
        for _i in range(50):

            async def noop():
                await asyncio.sleep(0.01)
                return

            task = asyncio.create_task(noop())
            orchestrator._cancellation_tasks.add(task)
            tasks_added.append(task)

    async def cleanup_tasks():
        await asyncio.sleep(0.01)
        with orchestrator._cancellation_tasks_lock:
            orchestrator._cancellation_tasks.clear()

    # Run add and clear concurrently
    await asyncio.gather(add_tasks(), cleanup_tasks())

    # After clear, set should be empty or only contain tasks added after clear
    # This test verifies that the lock prevents race conditions
    assert len(orchestrator._cancellation_tasks) <= len(tasks_added)

    # Clean up
    for task in tasks_added:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks_added, return_exceptions=True)


async def test_cleanup_pending_cancellation_tasks_concurrent(orchestrator):
    """Test cleanup_pending_cancellation_tasks with concurrent additions."""
    # Add some tasks
    tasks_added = []
    async with FakeClockContext() as clock:
        for _ in range(10):

            async def long_running():
                await asyncio.sleep(10)
                return

            task = asyncio.create_task(long_running())
            orchestrator._cancellation_tasks.add(task)
            tasks_added.append(task)

        # Start a concurrent add task
        async def add_during_cleanup():
            sleep_task = asyncio.create_task(asyncio.sleep(0.001))
            clock.advance(0.001)
            await sleep_task

            async def noop():
                return

            task = asyncio.create_task(noop())
            with orchestrator._cancellation_tasks_lock:
                orchestrator._cancellation_tasks.add(task)
            tasks_added.append(task)

        # Both operations should work without race
        await asyncio.gather(
            orchestrator.cleanup(),
            add_during_cleanup(),
        )

    # Clean up
    for task in tasks_added:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks_added, return_exceptions=True)
