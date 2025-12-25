"""Regression test for race condition fix in MemoryService.

Tests that _analysis_in_progress dict is accessed with proper lock
protection to prevent race conditions during concurrent eviction and cleanup.
"""

import asyncio
import pytest

from src.core.memory.config import MemoryConfiguration
from src.core.memory.repository import IMemoryRepository
from src.core.memory.service import MemoryService


class MockRepository(IMemoryRepository):
    """Mock repository for testing."""

    async def get_or_create_project_id(self, user_id: str, project_root: str) -> str:
        return f"{user_id}:{project_root}"

    async def store_session_summary(self, session_id: str, summary: dict) -> bool:
        return True


class TestMemoryServiceRaceConditionFix:
    """Tests for race condition fixes in MemoryService._analysis_in_progress."""

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
