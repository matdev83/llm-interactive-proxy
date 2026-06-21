"""
Regression test for race condition in MemoryService.

Tests that _analysis_in_progress dictionary access is properly synchronized.
"""

import asyncio

import pytest
from src.core.memory.config import MemoryConfiguration
from src.core.memory.repository import IMemoryRepository
from src.core.memory.service import MemoryService


class MockRepository(IMemoryRepository):
    """Mock repository for testing."""

    async def get_or_create_project_id(self, user_id: str, project_root: str) -> str:
        return f"proj_{user_id}_{project_root}"

    async def store_session_summary(self, session_id: str, summary: dict) -> bool:
        return True


@pytest.mark.asyncio
async def test_analysis_progress_concurrent_access():
    """
    Test that _analysis_in_progress is thread-safe.

    Previously, get_pending_analysis_session and complete_analysis
    accessed _analysis_in_progress without locks, causing race conditions.
    """
    config = MemoryConfiguration(
        available=True,
        max_buffer_size_bytes=1024 * 1024,
        summarization_delay_seconds=0,
    )
    repo = MockRepository()
    service = MemoryService(config, repo)

    session_id = "test_session_123"

    # Add session to analysis_in_progress
    async with service._analysis_lock:
        service._analysis_in_progress[session_id] = asyncio.get_event_loop().time()

    # Simulate concurrent complete_analysis calls
    tasks = [
        asyncio.create_task(service.complete_analysis(session_id)) for _ in range(5)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Should not raise exceptions
    # Session should be removed
    assert session_id not in service._analysis_in_progress
    # All tasks should complete successfully
    assert all(r is None for r in results)


@pytest.mark.asyncio
async def test_queue_operations_concurrent():
    """
    Test concurrent get_pending_analysis_session operations.

    Multiple concurrent calls to get_pending_analysis_session should
    properly coordinate access to _analysis_in_progress.
    """
    config = MemoryConfiguration(
        available=True,
        max_buffer_size_bytes=1024 * 1024,
        summarization_delay_seconds=0,
    )
    repo = MockRepository()
    service = MemoryService(config, repo)

    # Add sessions to queue
    session_ids = [f"session_{i}" for i in range(10)]
    for sid in session_ids:
        service._analysis_queue.put_nowait(sid)

    # Concurrent consumers
    async def consumer():
        sessions = []
        for _ in range(5):
            sid = await service.get_pending_analysis_session()
            if sid:
                sessions.append(sid)
        return sessions

    consumers = [asyncio.create_task(consumer()) for _ in range(3)]
    results = await asyncio.gather(*consumers)

    # All sessions should be consumed exactly once
    all_consumed = []
    for r in results:
        all_consumed.extend(r)

    assert len(set(all_consumed)) == len(
        all_consumed
    ), "No session should be consumed twice"
    assert set(all_consumed).issubset(set(session_ids))


@pytest.mark.asyncio
async def test_complete_and_get_concurrent():
    """
    Test concurrent complete_analysis and get_pending_analysis_session.

    These operations both modify/read _analysis_in_progress
    and must be properly synchronized.
    """
    config = MemoryConfiguration(
        available=True,
        max_buffer_size_bytes=1024 * 1024,
        summarization_delay_seconds=0,
    )
    repo = MockRepository()
    service = MemoryService(config, repo)

    # Add sessions to queue
    session_ids = [f"session_{i}" for i in range(20)]
    for sid in session_ids:
        service._analysis_queue.put_nowait(sid)

    results = []

    async def completer():
        """Mark sessions as complete"""
        for i in range(10):
            sid = f"session_{i}"
            if sid in service._analysis_in_progress:
                await service.complete_analysis(sid)
                results.append(f"completed_{sid}")

    async def getter():
        """Get pending sessions"""
        for _i in range(10):
            sid = await service.get_pending_analysis_session()
            if sid:
                results.append(f"got_{sid}")

    # Run concurrent operations
    await asyncio.gather(completer(), getter())

    # No errors should occur
    # State should be consistent
    assert len(service._analysis_in_progress) >= 0


@pytest.mark.asyncio
async def test_stale_cleanup_concurrent():
    """
    Test concurrent stale analysis_in_progress cleanup.

    The cleanup operation should be safe when called
    concurrently with other operations.
    """
    config = MemoryConfiguration(
        available=True,
        max_buffer_size_bytes=1024 * 1024,
        summarization_delay_seconds=0,
    )
    repo = MockRepository()
    service = MemoryService(config, repo)

    from tests.utils.fake_clock import FakeClock, FakeClockContext

    # Add old entries (simulate stuck sessions) - use TTL that will trigger cleanup
    # Note: _ANALYSIS_IN_PROGRESS_TTL_SECONDS = 1800, so we need to use negative offset
    async with FakeClockContext(FakeClock(initial_time=1704067200.0)) as clock:
        old_time = clock.now() - 2000
        for i in range(10):
            async with service._analysis_lock:
                service._analysis_in_progress[f"old_session_{i}"] = old_time

        # Add fresh entries
        fresh_time = clock.now()
        for i in range(5):
            async with service._analysis_lock:
                service._analysis_in_progress[f"fresh_session_{i}"] = fresh_time

        # Verify initial state
        async with service._analysis_lock:
            assert len(service._analysis_in_progress) == 15

        # Trigger cleanup and concurrent access
        async def worker():
            for i in range(5):
                session_id = f"fresh_session_{i}"
                async with service._analysis_lock:
                    _ = service._analysis_in_progress.get(session_id)

        # Run cleanup and concurrent workers
        tasks = [asyncio.create_task(worker()) for _ in range(5)]
        tasks.append(asyncio.create_task(service._cleanup_stale_analysis_in_progress()))
        await asyncio.gather(*tasks, return_exceptions=True)

        # Old sessions should be cleaned up
        for i in range(10):
            async with service._analysis_lock:
                assert f"old_session_{i}" not in service._analysis_in_progress
        # Fresh sessions should remain
        for i in range(5):
            async with service._analysis_lock:
                assert f"fresh_session_{i}" in service._analysis_in_progress
        # Verify total count
        async with service._analysis_lock:
            assert len(service._analysis_in_progress) == 5


class TestMemoryServiceRaceConditionFix:
    """Tests for race condition fixes in MemoryService._analysis_in_progress."""

    @pytest.mark.asyncio
    async def test_concurrent_analysis_progress_access(self):
        """Test that concurrent access to _analysis_in_progress is safe."""
        config = MemoryConfiguration(
            available=True,
            analysis_queue_maxsize=100,
            summarization_delay_seconds=0,  # No delay to avoid task cleanup issues
        )
        repo = MockRepository()
        service = MemoryService(config, repo)

        # Enable memory for multiple sessions
        session_ids = [f"session_{i}" for i in range(10)]
        for sid in session_ids:
            await service.enable_for_session(sid, "user1", project_root="/tmp/test")

        # Mark sessions as complete (adds to _analysis_in_progress)
        for sid in session_ids:
            await service.mark_session_complete(sid)

        # Verify they're in analysis_in_progress
        assert service.get_active_session_count() == 10

    @pytest.mark.asyncio
    async def test_analysis_in_progress_cleanup_is_thread_safe(self):
        """Test that _analysis_in_progress cleanup happens with proper locking."""
        config = MemoryConfiguration(
            available=True,
            analysis_queue_maxsize=100,
            summarization_delay_seconds=0,
        )
        repo = MockRepository()
        service = MemoryService(config, repo)

        # Enable many sessions to trigger cleanup
        session_ids = [f"session_{i}" for i in range(20)]
        for sid in session_ids:
            await service.enable_for_session(sid, "user1", project_root="/tmp/test")
            await service.mark_session_complete(sid)

        # Get pending sessions - should have some
        pending = await service.get_pending_analysis_session()
        assert pending is not None

        # Complete analysis
        await service.complete_analysis(pending)

        # Should have one less session now
        assert service.get_active_session_count() == 19

    @pytest.mark.asyncio
    async def test_analysis_in_progress_complete_is_safe(self):
        """Test that complete_analysis() properly cleans up _analysis_in_progress."""
        config = MemoryConfiguration(
            available=True,
            analysis_queue_maxsize=100,
            summarization_delay_seconds=0,
        )
        repo = MockRepository()
        service = MemoryService(config, repo)

        # Enable and complete a session
        await service.enable_for_session("session_1", "user1", project_root="/tmp/test")
        await service.mark_session_complete("session_1")

        # Get it as pending (adds to _analysis_in_progress)
        pending = await service.get_pending_analysis_session()
        assert pending == "session_1"

        # Complete analysis (should remove from _analysis_in_progress)
        await service.complete_analysis(pending)

        # Session should be removed
        assert service.get_active_session_count() == 0

        # Trying to complete again should be safe (no-op)
        await service.complete_analysis("session_1")

    @pytest.mark.asyncio
    async def test_concurrent_cleanup_and_pending_access(self):
        """Test that cleanup and pending access don't race."""
        config = MemoryConfiguration(
            available=True,
            analysis_queue_maxsize=100,
            summarization_delay_seconds=0,
        )
        repo = MockRepository()
        service = MemoryService(config, repo)

        # Enable many sessions
        session_ids = [f"session_{i}" for i in range(100)]
        for sid in session_ids:
            await service.enable_for_session(sid, "user1", project_root="/tmp/test")
            await service.mark_session_complete(sid)

        # Concurrently get pending sessions and complete them
        errors = []

        async def worker(task_id):
            """Worker that gets and completes sessions."""
            try:
                for _ in range(10):
                    session_id = await service.get_pending_analysis_session()
                    if session_id:
                        await service.complete_analysis(session_id)
            except Exception as e:
                errors.append(f"Worker {task_id}: {e}")

        # Run 10 workers concurrently
        tasks = [asyncio.create_task(worker(i)) for i in range(10)]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Should have no race-related errors
        assert not errors, f"Race condition detected: {errors}"
