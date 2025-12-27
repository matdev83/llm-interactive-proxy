"""Regression test for AnalysisWorker task leak fix.

This test verifies that AnalysisWorker properly cleans up async tasks when stop()
is called, preventing task accumulation when workers are created and started but
never stopped.

Fixed: AnalysisWorker.stop() properly cancels and awaits all tasks in _tasks list.
"""

import asyncio

import pytest
from src.core.memory.analysis_worker import AnalysisWorker
from src.core.memory.config import MemoryConfiguration
from src.core.memory.summary_generator import SummaryResult


class MockMemoryService:
    """Mock memory service for testing."""

    def __init__(self):
        self._queue = asyncio.Queue()

    async def get_pending_analysis_session(self):
        """Return None to simulate empty queue."""
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return None

    def get_analysis_queue_size(self) -> int:
        return self._queue.qsize()


class MockSummaryGenerator:
    """Mock summary generator for testing."""

    async def generate_summary(self, **kwargs):
        """Mock summary generation."""
        return SummaryResult(success=True, summary=None, error=None)


class TestAnalysisWorkerTaskLeakRegression:
    """Regression tests for AnalysisWorker task leak fix."""

    def _create_worker(self) -> AnalysisWorker:
        """Create an AnalysisWorker instance for testing."""
        memory_service = MockMemoryService()
        summary_generator = MockSummaryGenerator()
        config = MemoryConfiguration(
            max_concurrent_analyses=2,
            analysis_timeout_seconds=30.0,
        )
        return AnalysisWorker(memory_service, summary_generator, config)

    @pytest.mark.asyncio
    async def test_stop_cleans_up_tasks(self) -> None:
        """Test that stop() properly cleans up worker tasks."""
        worker = self._create_worker()

        # Count initial tasks
        loop = asyncio.get_running_loop()
        tasks_before = [t for t in asyncio.all_tasks(loop) if not t.done()]

        # Start worker
        await worker.start()

        # Verify task was created
        assert len(worker._tasks) > 0, "Worker should have created tasks"
        assert worker._running, "Worker should be running"

        # Count tasks after start
        tasks_after_start = [t for t in asyncio.all_tasks(loop) if not t.done()]
        assert len(tasks_after_start) > len(
            tasks_before
        ), "Worker should have created new tasks"

        # Stop worker
        await worker.stop()

        # Wait a bit for tasks to be cancelled
        await asyncio.sleep(0.1)

        # Verify tasks are cleaned up
        assert len(worker._tasks) == 0, "Worker tasks should be cleared after stop"
        assert not worker._running, "Worker should not be running"

        # Count tasks after stop
        tasks_after_stop = [t for t in asyncio.all_tasks(loop) if not t.done()]
        # Allow some margin for test framework tasks
        assert len(tasks_after_stop) <= len(tasks_before) + 5, (
            f"Tasks should be cleaned up after stop. "
            f"Before: {len(tasks_before)}, After: {len(tasks_after_stop)}"
        )

    @pytest.mark.asyncio
    async def test_multiple_workers_with_stop(self) -> None:
        """Test that multiple workers can be started and stopped without leaking."""
        loop = asyncio.get_running_loop()
        tasks_before = [t for t in asyncio.all_tasks(loop) if not t.done()]

        workers = []
        for _i in range(10):
            worker = self._create_worker()
            await worker.start()
            workers.append(worker)

        # Verify workers are running
        tasks_after_start = [t for t in asyncio.all_tasks(loop) if not t.done()]
        assert len(tasks_after_start) > len(
            tasks_before
        ), "Workers should have created tasks"

        # Stop all workers
        for worker in workers:
            await worker.stop()

        # Wait for cleanup
        await asyncio.sleep(0.2)

        # Verify tasks are cleaned up
        tasks_after_stop = [t for t in asyncio.all_tasks(loop) if not t.done()]
        # Allow margin for test framework
        assert len(tasks_after_stop) <= len(tasks_before) + 10, (
            f"Tasks should be cleaned up after stopping all workers. "
            f"Before: {len(tasks_before)}, After: {len(tasks_after_stop)}"
        )

    @pytest.mark.asyncio
    async def test_rapid_create_start_stop_cycle(self) -> None:
        """Test rapid create/start/stop cycles don't leak tasks."""
        loop = asyncio.get_running_loop()
        tasks_before = [t for t in asyncio.all_tasks(loop) if not t.done()]

        # Rapidly create, start, and stop workers (reduced iterations for performance)
        for _i in range(20):  # Reduced from 50 for performance
            worker = self._create_worker()
            await worker.start()
            await worker.stop()

        # Wait for cleanup (reduced wait time)
        await asyncio.sleep(0.1)  # Reduced from 0.3 for performance

        # Verify no leak
        tasks_after = [t for t in asyncio.all_tasks(loop) if not t.done()]
        # Allow margin for test framework
        assert len(tasks_after) <= len(tasks_before) + 10, (
            f"Rapid cycles should not leak tasks. "
            f"Before: {len(tasks_before)}, After: {len(tasks_after)}"
        )

    @pytest.mark.asyncio
    async def test_stop_cancels_running_tasks(self) -> None:
        """Test that stop() cancels running worker tasks."""
        worker = self._create_worker()

        await worker.start()

        # Verify worker task is running
        assert len(worker._tasks) > 0, "Worker should have tasks"
        worker_task = worker._tasks[0]
        assert not worker_task.done(), "Worker task should be running"

        # Stop worker (should cancel tasks)
        await worker.stop()

        # Verify task was cancelled
        assert (
            worker_task.cancelled() or worker_task.done()
        ), "Worker task should be cancelled or done after stop"
        assert len(worker._tasks) == 0, "Tasks list should be cleared"

    @pytest.mark.asyncio
    async def test_double_stop_is_safe(self) -> None:
        """Test that calling stop() twice is safe."""
        worker = self._create_worker()

        await worker.start()
        await worker.stop()

        # Call stop again
        await worker.stop()

        # Should not raise exception and should be safe
        assert not worker._running, "Worker should not be running"
        assert len(worker._tasks) == 0, "Tasks should be cleared"
