"""Regression test for MemoryService session states memory leak fix.

This test verifies that sessions that fail to queue for analysis are properly
cleaned up to prevent unbounded memory growth in _session_states.
"""

import pytest
from src.core.memory.config import MemoryConfiguration
from src.core.memory.service import MemoryService


class MockMemoryRepository:
    """Mock repository for testing."""

    async def initialize_schema(self) -> None:
        pass

    async def save_session_summary(self, summary) -> None:
        pass

    async def get_recent_sessions(
        self,
        user_id: str,
        limit: int,
        tenant_id=None,
        project_id=None,
        project_root=None,
    ) -> list:
        return []

    async def delete_old_sessions(self, before_date) -> int:
        return 0

    async def get_or_create_project_id(self, user_id: str, project_root: str) -> str:
        return f"project-{user_id}-{project_root}"


class TestMemoryServiceSessionStatesLeakRegression:
    """Regression tests for MemoryService session states memory leak fix."""

    @pytest.fixture
    def config(self):
        """Create memory configuration with small queue."""
        return MemoryConfiguration(
            available=True,
            analysis_queue_maxsize=2,  # Small queue to simulate backpressure
            summarization_delay_seconds=0,  # Immediate analysis
            require_project_discovery=False,  # Allow sessions without project root
        )

    @pytest.fixture
    def repository(self):
        """Create mock repository."""
        return MockMemoryRepository()

    @pytest.fixture
    def memory_service(self, config, repository):
        """Create memory service."""
        return MemoryService(config, repository)

    @pytest.mark.asyncio
    async def test_sessions_failing_to_queue_are_cleaned_up(
        self, memory_service: MemoryService
    ) -> None:
        """Test that sessions that fail to queue are cleaned up from _session_states."""
        # Enable many sessions (more than queue size)
        num_sessions = 10

        for i in range(num_sessions):
            session_id = f"session-{i}"
            await memory_service.enable_for_session(
                session_id,
                user_id="test-user",
                project_root=f"/project/{i}",
            )
            # Mark sessions as complete (queues for analysis)
            # With queue size=2, only first 2 will be queued, rest will be dropped
            await memory_service.mark_session_complete(session_id)

        # Sessions that failed to queue should be cleaned up
        # Only sessions that were successfully queued should remain
        session_count = memory_service.get_active_session_count()
        queue_size = memory_service.get_analysis_queue_size()

        # After queue fills up, sessions that fail to queue should be removed
        # Expected: Only queued sessions remain (at most queue size)
        assert session_count <= queue_size, (
            f"Session count ({session_count}) exceeded queue size ({queue_size}). "
            "Sessions that failed to queue were not cleaned up."
        )

    @pytest.mark.asyncio
    async def test_sessions_processed_from_queue_are_cleaned_up(
        self, memory_service: MemoryService
    ) -> None:
        """Test that sessions processed from queue are cleaned up."""
        # Enable and mark complete sessions
        num_sessions = 5
        for i in range(num_sessions):
            session_id = f"session-{i}"
            await memory_service.enable_for_session(
                session_id,
                user_id="test-user",
                project_root=f"/project/{i}",
            )
            await memory_service.mark_session_complete(session_id)

        # Process sessions from queue
        processed_count = 0
        while processed_count < num_sessions:
            session_id = await memory_service.get_pending_analysis_session()
            if session_id is None:
                break
            # Complete analysis to clean up session
            await memory_service.complete_analysis(session_id)
            processed_count += 1

        # After processing, sessions should be cleaned up
        session_count = memory_service.get_active_session_count()
        # Some sessions may remain if they're still in queue or analysis_in_progress
        # But they should be bounded
        from src.core.memory.service import _MAX_SESSION_STATES

        assert session_count <= _MAX_SESSION_STATES, (
            f"Session count ({session_count}) exceeded max limit. "
            "Sessions were not properly cleaned up after processing."
        )

    @pytest.mark.asyncio
    async def test_worker_crash_scenario_sessions_bounded(
        self, memory_service: MemoryService
    ) -> None:
        """Test that sessions remain bounded even if worker crashes."""
        # Enable and mark complete sessions
        num_sessions = 10
        for i in range(num_sessions):
            session_id = f"session-{i}"
            await memory_service.enable_for_session(
                session_id,
                user_id="test-user",
                project_root=f"/project/{i}",
            )
            await memory_service.mark_session_complete(session_id)

        # Simulate worker processing some sessions but crashing before completion
        processed_count = 0
        while processed_count < 2:  # Process only 2 sessions
            session_id = await memory_service.get_pending_analysis_session()
            if session_id is None:
                break
            # Don't call complete_analysis to simulate worker crash
            processed_count += 1

        # Add more sessions - they should still be bounded
        for i in range(num_sessions, num_sessions + 10):
            session_id = f"session-{i}"
            await memory_service.enable_for_session(
                session_id,
                user_id="test-user",
            )
            await memory_service.mark_session_complete(session_id)

        # Sessions should be bounded even after worker crash scenario
        from src.core.memory.service import _MAX_SESSION_STATES

        session_count = memory_service.get_active_session_count()
        assert session_count <= _MAX_SESSION_STATES, (
            f"Session count ({session_count}) exceeded max limit after worker crash scenario. "
            "Sessions accumulated unbounded."
        )

    @pytest.mark.asyncio
    async def test_queue_full_cleanup_removes_session_state(
        self, memory_service: MemoryService
    ) -> None:
        """Test that when queue is full, failed sessions are removed from _session_states."""
        # Fill queue to capacity
        queue_size = memory_service._analysis_queue.maxsize

        # Enable sessions up to queue size
        for i in range(queue_size):
            session_id = f"session-{i}"
            await memory_service.enable_for_session(
                session_id,
                user_id="test-user",
                project_root=f"/project/{i}",
            )
            await memory_service.mark_session_complete(session_id)

        # Verify queue is full
        assert memory_service.get_analysis_queue_size() == queue_size

        # Try to add more sessions - these should fail to queue and be cleaned up
        failed_session_id = "session-failed"
        await memory_service.enable_for_session(
            failed_session_id,
            user_id="test-user",
            project_root="/project/failed",
        )
        result = await memory_service.mark_session_complete(failed_session_id)

        # Session should fail to queue
        assert result is False, "Session should fail to queue when queue is full"

        # Failed session should be removed from _session_states
        session_count = memory_service.get_active_session_count()
        # Only queued sessions should remain
        assert session_count <= queue_size, (
            f"Failed session was not cleaned up. "
            f"Session count ({session_count}) exceeds queue size ({queue_size})."
        )

        # Verify failed session is not in _session_states
        async with memory_service._state_lock:
            assert (
                failed_session_id not in memory_service._session_states
            ), "Failed session was not removed from _session_states."
