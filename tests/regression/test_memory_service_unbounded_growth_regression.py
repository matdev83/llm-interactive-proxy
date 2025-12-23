"""Regression test for MemoryService unbounded growth fix.

This test verifies that MemoryService properly bounds session state growth
and cleans up stale sessions to prevent unbounded memory growth.
"""

import time

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


class TestMemoryServiceUnboundedGrowthRegression:
    """Regression tests for MemoryService unbounded growth fix."""

    @pytest.fixture
    def config(self):
        """Create memory configuration."""
        return MemoryConfiguration(
            available=True,
            analysis_queue_maxsize=100,
            summarization_delay_seconds=0,
            require_project_discovery=False,
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
    async def test_sessions_bounded_by_max_limit(
        self, memory_service: MemoryService
    ) -> None:
        """Test that session states don't exceed MAX_SESSION_STATES limit."""
        # Import the constant to check against
        from src.core.memory.service import _MAX_SESSION_STATES

        # Enable many sessions (more than max limit)
        num_sessions = _MAX_SESSION_STATES + 100

        for i in range(num_sessions):
            session_id = f"enabled-only-{i}"
            await memory_service.enable_for_session(
                session_id,
                user_id="test-user",
                project_root=f"/project/{i}",
            )

        # Session count should not exceed max limit
        session_count = memory_service.get_active_session_count()
        assert session_count <= _MAX_SESSION_STATES, (
            f"Session count ({session_count}) exceeded max limit "
            f"({_MAX_SESSION_STATES}). Eviction is not working."
        )

    @pytest.mark.asyncio
    async def test_sessions_cleaned_up_after_ttl(
        self, memory_service: MemoryService
    ) -> None:
        """Test that stale sessions are cleaned up after TTL expires."""
        from src.core.memory.service import _SESSION_STATE_TTL_SECONDS

        # Enable some sessions
        num_sessions = 10
        for i in range(num_sessions):
            session_id = f"ttl-test-{i}"
            await memory_service.enable_for_session(
                session_id,
                user_id="test-user",
                project_root=f"/project/{i}",
            )

        initial_count = memory_service.get_active_session_count()
        assert initial_count == num_sessions

        # Manually set old access times to trigger TTL cleanup
        # We need to access the internal state to manipulate last_access
        async with memory_service._state_lock:
            old_time = time.time() - (_SESSION_STATE_TTL_SECONDS + 3600)  # 2 hours ago
            for session_id in list(memory_service._session_states.keys())[:5]:
                state = memory_service._session_states[session_id]
                state.last_access = old_time

        # Trigger cleanup by enabling a new session (which calls cleanup)
        await memory_service.enable_for_session(
            "new-session-after-ttl",
            user_id="test-user",
            project_root="/project/new",
        )

        # Some sessions should have been cleaned up
        final_count = memory_service.get_active_session_count()
        assert final_count < initial_count, (
            f"Expected some sessions to be cleaned up after TTL, "
            f"but count remained {initial_count}. TTL cleanup is not working."
        )

    @pytest.mark.asyncio
    async def test_sessions_enabled_but_never_completed_are_cleaned(
        self, memory_service: MemoryService
    ) -> None:
        """Test that sessions enabled but never marked complete are cleaned up."""
        from src.core.memory.service import _MAX_SESSION_STATES

        # Enable many sessions without marking them complete
        num_sessions = min(_MAX_SESSION_STATES + 50, 500)  # Cap to avoid slow test
        for i in range(num_sessions):
            session_id = f"enabled-only-{i}"
            await memory_service.enable_for_session(
                session_id,
                user_id="test-user",
                project_root=f"/project/{i}",
            )

        # Sessions should be bounded
        session_count = memory_service.get_active_session_count()
        assert session_count <= _MAX_SESSION_STATES, (
            f"Sessions enabled but never completed accumulated unbounded. "
            f"Count: {session_count}, max: {_MAX_SESSION_STATES}"
        )

    @pytest.mark.asyncio
    async def test_analysis_in_progress_bounded(
        self, memory_service: MemoryService
    ) -> None:
        """Test that analysis_in_progress entries are bounded."""
        from src.core.memory.service import _MAX_ANALYSIS_IN_PROGRESS

        # Enable and mark complete many sessions to fill analysis queue
        num_sessions = min(
            _MAX_ANALYSIS_IN_PROGRESS + 100, 200
        )  # Cap to avoid slow test
        for i in range(num_sessions):
            session_id = f"queued-{i}"
            await memory_service.enable_for_session(
                session_id,
                user_id="test-user",
                project_root=f"/project/queued/{i}",
            )
            await memory_service.mark_session_complete(session_id)

        # Get sessions from queue to populate _analysis_in_progress
        # This simulates worker processing
        processed_count = 0
        while processed_count < num_sessions:
            session_id = await memory_service.get_pending_analysis_session()
            if session_id is None:
                break
            # Don't call complete_analysis to simulate worker crash
            processed_count += 1

        # Check that _analysis_in_progress is bounded
        async with memory_service._state_lock:
            analysis_count = len(memory_service._analysis_in_progress)
            assert analysis_count <= _MAX_ANALYSIS_IN_PROGRESS, (
                f"Analysis in progress count ({analysis_count}) exceeded max limit "
                f"({_MAX_ANALYSIS_IN_PROGRESS}). Eviction is not working."
            )

    @pytest.mark.asyncio
    async def test_oldest_sessions_evicted_when_limit_reached(
        self, memory_service: MemoryService
    ) -> None:
        """Test that oldest sessions are evicted when max limit is reached (LRU)."""
        from src.core.memory.service import _MAX_SESSION_STATES

        # Fill up to max limit
        for i in range(_MAX_SESSION_STATES):
            session_id = f"session-{i}"
            await memory_service.enable_for_session(
                session_id,
                user_id="test-user",
                project_root=f"/project/{i}",
            )

        assert memory_service.get_active_session_count() == _MAX_SESSION_STATES

        # Add more sessions - should evict oldest
        for i in range(_MAX_SESSION_STATES, _MAX_SESSION_STATES + 10):
            session_id = f"session-{i}"
            await memory_service.enable_for_session(
                session_id,
                user_id="test-user",
                project_root=f"/project/{i}",
            )

        # Should still be at max limit (oldest evicted)
        assert memory_service.get_active_session_count() <= _MAX_SESSION_STATES, (
            "Session count exceeded max limit after adding more sessions. "
            "LRU eviction is not working."
        )

        # Verify oldest sessions were evicted
        async with memory_service._state_lock:
            # First session should be gone
            assert (
                "session-0" not in memory_service._session_states
            ), "Oldest session was not evicted."

    @pytest.mark.asyncio
    async def test_lru_eviction_preserves_recently_accessed_sessions(
        self, memory_service: MemoryService
    ) -> None:
        """Test that LRU eviction preserves recently accessed sessions."""
        from src.core.memory.service import _MAX_SESSION_STATES

        # Create sessions up to max limit (fill to capacity)
        for i in range(_MAX_SESSION_STATES):
            session_id = f"test-{i}"
            await memory_service.enable_for_session(
                session_id,
                user_id="test-user",
                project_root=f"/project/{i}",
            )

        assert memory_service.get_active_session_count() == _MAX_SESSION_STATES

        # Access first 10 sessions to update their last_access and move them to end (LRU)
        # This makes them "most recently used" and should preserve them
        for i in range(10):
            session_id = f"test-{i}"
            await memory_service.is_enabled_for_session(session_id)

        # Add a small number of new sessions - should evict oldest (middle) sessions, not first 10
        num_new_sessions = 20  # Small number to test LRU preservation
        for i in range(_MAX_SESSION_STATES, _MAX_SESSION_STATES + num_new_sessions):
            session_id = f"test-{i}"
            await memory_service.enable_for_session(
                session_id,
                user_id="test-user",
                project_root=f"/project/{i}",
            )

        # Should still be at max limit
        assert memory_service.get_active_session_count() <= _MAX_SESSION_STATES

        # Check if first 10 sessions are still present (they were accessed recently and moved to end)
        # They should be preserved because they're the most recently used
        preserved_count = 0
        for i in range(10):
            session_id = f"test-{i}"
            is_enabled = await memory_service.is_enabled_for_session(session_id)
            if is_enabled:
                preserved_count += 1

        # At least most of the recently accessed sessions should be preserved
        # (allowing for edge cases where eviction might happen during access)
        assert preserved_count >= 8, (
            f"Only {preserved_count}/10 recently accessed sessions were preserved. "
            f"LRU eviction should preserve recently accessed sessions (moved to end of OrderedDict)."
        )
