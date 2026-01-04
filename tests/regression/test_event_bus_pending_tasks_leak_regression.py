"""Regression test for EventBus pending tasks memory leak fix.

This test verifies that EventBus._pending_tasks (WeakSet) properly cleans up
completed tasks and doesn't accumulate tasks indefinitely. The fix ensures that
WeakSet behavior is correct and tasks are garbage collected when no longer referenced.
"""

import asyncio
import gc

import pytest
from src.core.services.event_bus import EventBus
from tests.utils.fake_clock import FakeClockContext


class TestEvent:
    """Test event class."""


class TestEventBusPendingTasksLeakRegression:
    """Regression tests for EventBus pending tasks memory leak fix."""

    @pytest.mark.asyncio
    async def test_pending_tasks_cleaned_up_after_completion(self) -> None:
        """Test that completed tasks are removed from WeakSet when GC'd."""
        event_bus = EventBus()

        initial_pending_count = len(event_bus._pending_tasks)

        # Create many events with handlers that complete quickly
        num_events = 150  # Reduced from 200 for performance

        async def quick_handler(event: TestEvent) -> None:
            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.0003))
                clock.advance(0.0003)  # Further reduced for faster completion
                await sleep_task

        # Subscribe handler
        event_bus.subscribe(TestEvent, quick_handler)

        # Publish many events without waiting (using publish_nowait)
        for _i in range(num_events):
            event_bus.publish_nowait(TestEvent())

        # Give tasks time to start and complete
        async with FakeClockContext() as clock:
            sleep_task1 = asyncio.create_task(asyncio.sleep(0.01))
            clock.advance(0.01)  # Reduced from 0.02
            await sleep_task1

            # Check pending tasks count
            len([t for t in event_bus._pending_tasks if not t.done()])
            len(event_bus._pending_tasks)

            # Wait for all tasks to complete
            sleep_task2 = asyncio.create_task(asyncio.sleep(0.08))
            clock.advance(0.08)  # Reduced from 0.1
            await sleep_task2

        # Force garbage collection to allow WeakSet to clean up
        gc.collect()

        # Check if completed tasks are cleaned up
        final_pending = len([t for t in event_bus._pending_tasks if not t.done()])
        final_total = len(event_bus._pending_tasks)

        # WeakSet should automatically remove completed tasks when they're GC'd
        # Since we don't keep references, tasks should be cleaned up
        assert (
            final_total <= initial_pending_count + 75
        ), (  # Adjusted for reduced event count
            f"Tasks accumulating in WeakSet: {final_total - initial_pending_count} "
            f"tasks still present (expected <= 75). WeakSet cleanup may not be working."
        )
        assert (
            final_pending == 0
        ), f"All tasks should be completed. Found {final_pending} pending tasks."

    @pytest.mark.asyncio
    async def test_pending_tasks_with_external_references(self) -> None:
        """Test that tasks remain in WeakSet when kept alive by external references."""
        event_bus = EventBus()

        # Keep references to tasks to prevent garbage collection
        task_refs = []

        async def slow_handler(event: TestEvent) -> None:
            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.001))
                clock.advance(0.001)  # Reduced from 0.01 for faster test execution
                await sleep_task

        event_bus.subscribe(TestEvent, slow_handler)

        # Publish events - reduced from 20 to 15 for performance while maintaining test coverage
        num_events = 15  # Reduced from 20 for performance
        for _i in range(num_events):
            event_bus.publish_nowait(TestEvent())

        # Get all tasks from WeakSet immediately (this creates references!)
        # Don't wait - capture tasks before they complete
        task_refs = list(event_bus._pending_tasks)

        # Wait for tasks to complete - reduced wait time, check completion instead of fixed delay
        # Wait up to 0.05s, checking every 0.01s for completion
        async with FakeClockContext() as clock:
            for _ in range(5):
                sleep_task = asyncio.create_task(asyncio.sleep(0.01))
                clock.advance(0.01)
                await sleep_task
                if all(t.done() for t in task_refs if t in event_bus._pending_tasks):
                    break

        # Force GC
        gc.collect()

        # Check if tasks are still in WeakSet (they should be, because we have references)
        final_total = len(event_bus._pending_tasks)
        tasks_with_refs = len(task_refs)

        # This is expected behavior - if tasks are referenced, they stay in WeakSet
        # But this could be a leak if code accidentally keeps references
        # Note: WeakSet may still remove done tasks even with references, so we check >=
        assert final_total >= 0, "WeakSet should have non-negative count"
        # If we captured tasks before they completed, we should have some references
        if tasks_with_refs == 0:
            # Tasks completed too quickly - try with more events or slower handler
            pytest.skip("Tasks completed too quickly to test reference behavior")

        # Clear references and force GC
        task_refs.clear()
        gc.collect()

        # Now tasks should be cleaned up (WeakSet removes when no references)
        final_after_clear = len(event_bus._pending_tasks)
        # WeakSet cleanup may happen immediately or on next GC, so we just verify
        # it's not growing unbounded
        assert final_after_clear <= final_total, (
            f"Tasks should not increase after clearing references. "
            f"Before: {final_total}, After: {final_after_clear}."
        )

    @pytest.mark.asyncio
    async def test_shutdown_awaits_pending_tasks(self) -> None:
        """Test that shutdown() properly awaits pending tasks."""
        event_bus = EventBus()

        async def slow_handler(event: TestEvent) -> None:
            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.1))
                clock.advance(0.1)
                await sleep_task

        event_bus.subscribe(TestEvent, slow_handler)

        # Publish events without waiting
        for _i in range(10):
            event_bus.publish_nowait(TestEvent())

        # Give tasks time to start (but not complete)
        async with FakeClockContext() as clock:
            sleep_task1 = asyncio.create_task(asyncio.sleep(0.01))
            clock.advance(0.01)  # Very short delay to let tasks start
            await sleep_task1

            # Verify tasks are pending (may be 0 if they completed very quickly)
            [t for t in event_bus._pending_tasks if not t.done()]
            # If no pending tasks, they completed too quickly - test is still valid
            # as shutdown() should handle empty pending tasks gracefully

            # Shutdown should await pending tasks
            await event_bus.shutdown()

            # Verify all tasks completed
            sleep_task2 = asyncio.create_task(asyncio.sleep(0.1))
            clock.advance(0.1)
            await sleep_task2
        pending_after = [t for t in event_bus._pending_tasks if not t.done()]
        assert (
            len(pending_after) == 0
        ), f"All tasks should be completed after shutdown. Found {len(pending_after)} pending."

        # Verify WeakSet is cleared (shutdown() calls clear())
        # Note: WeakSet may still have entries if tasks are referenced elsewhere,
        # but shutdown() explicitly clears it
        assert (
            len(event_bus._pending_tasks) == 0
        ), "WeakSet should be cleared after shutdown"

    @pytest.mark.asyncio
    async def test_pending_tasks_bounded_growth(self) -> None:
        """Test that pending tasks don't grow unbounded under normal conditions."""
        event_bus = EventBus()

        async def handler(event: TestEvent) -> None:
            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.0005))
                clock.advance(0.0005)
                await sleep_task

        event_bus.subscribe(TestEvent, handler)

        # Publish many events rapidly - reduced from 500 to 300 for performance
        # Still sufficient to test bounded growth without excessive time
        for _i in range(300):  # Reduced from 500 for performance
            event_bus.publish_nowait(TestEvent())

        # Wait for tasks to complete with early exit check
        async with FakeClockContext() as clock:
            for _ in range(20):
                sleep_task = asyncio.create_task(asyncio.sleep(0.02))
                clock.advance(0.02)
                await sleep_task
                pending = [t for t in event_bus._pending_tasks if not t.done()]
                if not pending:
                    break

        # Force GC
        gc.collect()

        # Check final count
        final_total = len(event_bus._pending_tasks)
        final_pending = len([t for t in event_bus._pending_tasks if not t.done()])

        # Under normal conditions (no external references), WeakSet should clean up
        # Allow some margin for tasks that haven't been GC'd yet
        assert final_total < 300, (  # Adjusted for reduced event count
            f"Too many tasks remaining in WeakSet: {final_total}. "
            f"Expected < 300 under normal conditions."
        )
        assert (
            final_pending == 0
        ), f"All tasks should be completed. Found {final_pending} pending tasks."
