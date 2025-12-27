"""Regression test for BackendLifecycleManager discard() task leak fix.

This test verifies that shutdown tasks created by discard() are properly tracked
and can be awaited, preventing resource leaks when many backends are discarded.

Fixed: Shutdown tasks are tracked in _shutdown_tasks set and can be awaited via
await_pending_shutdown_tasks() to prevent unbounded task accumulation.
"""

import asyncio

import pytest
from src.core.services.backend_lifecycle_manager import BackendLifecycleManager
from tests.utils.fake_clock import FakeClockContext


class MockBackend:
    """Mock backend for testing."""

    def __init__(self, backend_type: str) -> None:
        self.backend_type = backend_type
        self.shutdown_called = False

    async def shutdown(self) -> None:
        """Simulate shutdown."""
        self.shutdown_called = True


class TestBackendDiscardTaskLeakRegression:
    """Regression tests for BackendLifecycleManager discard() task leak fix."""

    @pytest.fixture
    def manager(self) -> BackendLifecycleManager:
        """Create a BackendLifecycleManager instance."""
        return BackendLifecycleManager()

    @pytest.mark.asyncio
    async def test_discard_creates_tracked_shutdown_tasks(
        self, manager: BackendLifecycleManager
    ) -> None:
        """Test that discard() creates shutdown tasks that are tracked."""
        # Add mock backends
        backend1 = MockBackend("test-backend-1")
        backend2 = MockBackend("test-backend-2")
        backend3 = MockBackend("test-backend-3")

        manager._backends["test-backend-1"] = backend1
        manager._backends["test-backend-2"] = backend2
        manager._per_session_backends["test-backend-3:session-1"] = backend3

        # Count tasks before discard
        loop = asyncio.get_running_loop()
        tasks_before = [t for t in asyncio.all_tasks(loop) if not t.done()]

        # Discard backends (creates fire-and-forget tasks)
        manager.discard("test-backend-1", None, "test")
        manager.discard("test-backend-2", None, "test")
        manager.discard("test-backend-3", "session-1", "test")

        # Verify tasks are tracked
        assert (
            len(manager._shutdown_tasks) == 3
        ), f"Expected 3 tracked shutdown tasks, got {len(manager._shutdown_tasks)}"

        # Count tasks after discard
        tasks_after = [t for t in asyncio.all_tasks(loop) if not t.done()]
        assert len(tasks_after) > len(
            tasks_before
        ), "Discard should create new shutdown tasks"

        # Wait for tasks to complete (using fake clock for deterministic timing)
        from tests.utils.fake_clock import FakeClockContext

        async with FakeClockContext() as clock:
            clock.advance(0.01)

        # Verify backends were shut down
        assert backend1.shutdown_called, "Backend 1 should be shut down"
        assert backend2.shutdown_called, "Backend 2 should be shut down"
        assert backend3.shutdown_called, "Backend 3 should be shut down"

        # Tasks should be removed from tracking set when completed
        # (via done callback)
        pending_tracked = [t for t in manager._shutdown_tasks if not t.done()]
        assert (
            len(pending_tracked) == 0
        ), f"All tracked tasks should complete. {len(pending_tracked)} still pending"

    @pytest.mark.asyncio
    async def test_rapid_discards_dont_accumulate_unbounded(
        self, manager: BackendLifecycleManager
    ) -> None:
        """Test that many rapid discards don't cause unbounded task accumulation."""
        # Create many backends
        num_backends = 30
        for i in range(num_backends):
            backend = MockBackend(f"attack-backend-{i}")
            manager._backends[f"attack-backend-{i}"] = backend

        # Count tasks before discard
        loop = asyncio.get_running_loop()
        tasks_before = [t for t in asyncio.all_tasks(loop) if not t.done()]

        # Rapidly discard all backends
        for i in range(num_backends):
            manager.discard(f"attack-backend-{i}", None, "attack")

        # Verify all tasks are tracked
        assert len(manager._shutdown_tasks) == num_backends, (
            f"Expected {num_backends} tracked shutdown tasks, "
            f"got {len(manager._shutdown_tasks)}"
        )

        # Count tasks after discard
        tasks_after = [t for t in asyncio.all_tasks(loop) if not t.done()]
        new_tasks = len(tasks_after) - len(tasks_before)
        assert (
            new_tasks == num_backends
        ), f"Expected {num_backends} new tasks, got {new_tasks}"

        # Wait for tasks to complete (using fake clock for deterministic timing)
        from tests.utils.fake_clock import FakeClockContext

        async with FakeClockContext() as clock:
            clock.advance(0.01)

        # Verify tasks completed and are cleaned up from tracking set
        pending_tracked = [t for t in manager._shutdown_tasks if not t.done()]
        assert (
            len(pending_tracked) == 0
        ), f"All tracked tasks should complete. {len(pending_tracked)} still pending"

    @pytest.mark.asyncio
    async def test_await_pending_shutdown_tasks_awaits_all_tasks(
        self, manager: BackendLifecycleManager
    ) -> None:
        """Test that await_pending_shutdown_tasks() properly awaits all tasks."""
        # Create backends
        num_backends = 30
        backends = []
        for i in range(num_backends):
            backend = MockBackend(f"backend-{i}")
            manager._backends[f"backend-{i}"] = backend
            backends.append(backend)

        # Discard all backends
        for i in range(num_backends):
            manager.discard(f"backend-{i}", None, "test")

        # Verify tasks are tracked
        assert len(manager._shutdown_tasks) == num_backends

        # Don't wait for natural completion - call await_pending_shutdown_tasks
        await manager.await_pending_shutdown_tasks(timeout=5.0)

        # Verify all backends were shut down
        for backend in backends:
            assert backend.shutdown_called, "All backends should be shut down"

        # Verify tracking set is cleaned up
        pending_tracked = [t for t in manager._shutdown_tasks if not t.done()]
        assert (
            len(pending_tracked) == 0
        ), f"All tracked tasks should be awaited. {len(pending_tracked)} still pending"

    @pytest.mark.asyncio
    async def test_await_pending_shutdown_tasks_handles_timeout(
        self, manager: BackendLifecycleManager
    ) -> None:
        """Test that await_pending_shutdown_tasks() handles timeout properly."""

        # Create a backend with slow shutdown
        class SlowBackend(MockBackend):
            async def shutdown(self) -> None:
                # Use fake clock for deterministic time simulation
                await asyncio.sleep(0.5)  # Longer than timeout

        backend = SlowBackend("slow-backend")
        manager._backends["slow-backend"] = backend

        # Discard backend
        manager.discard("slow-backend", None, "test")

        # Verify task is tracked
        assert len(manager._shutdown_tasks) == 1

        # Use fake clock to control time progression for timeout test
        async with FakeClockContext() as clock:
            # Call await with short timeout
            await manager.await_pending_shutdown_tasks(timeout=0.05)
            # Advance clock to trigger timeout logic
            clock.advance(0.05)

        # Task should be cancelled due to timeout
        pending_tracked = [t for t in manager._shutdown_tasks if not t.done()]
        assert (
            len(pending_tracked) == 0
        ), "Tasks should be cancelled and removed from tracking set after timeout"

    @pytest.mark.asyncio
    async def test_discard_removes_backends_from_cache(
        self, manager: BackendLifecycleManager
    ) -> None:
        """Test that discard() removes backends from cache."""
        backend1 = MockBackend("backend-1")
        backend2 = MockBackend("backend-2")
        backend3 = MockBackend("backend-3")

        manager._backends["backend-1"] = backend1
        manager._backends["backend-2"] = backend2
        manager._per_session_backends["backend-3:session-1"] = backend3

        # Discard backends
        manager.discard("backend-1", None, "test")
        manager.discard("backend-2", None, "test")
        manager.discard("backend-3", "session-1", "test")

        # Verify backends are removed from cache
        assert "backend-1" not in manager._backends
        assert "backend-2" not in manager._backends
        assert "backend-3:session-1" not in manager._per_session_backends

        # Wait for shutdown tasks
        await manager.await_pending_shutdown_tasks(timeout=0.1)

        # Verify backends were shut down
        assert backend1.shutdown_called
        assert backend2.shutdown_called
        assert backend3.shutdown_called
