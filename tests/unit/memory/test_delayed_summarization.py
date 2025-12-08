"""Test delayed session summarization functionality."""

import asyncio
import contextlib
from unittest.mock import AsyncMock

import pytest
from src.core.memory.config import MemoryConfiguration
from src.core.memory.service import MemoryService


@pytest.fixture
def delayed_config() -> MemoryConfiguration:
    """Create test configuration with short delay."""
    return MemoryConfiguration(
        available=True,
        default_enabled=True,
        summarization_delay_seconds=2,  # Short delay for tests
        require_project_discovery=False,  # Don't require project discovery in tests
    )


@pytest.fixture
def immediate_config() -> MemoryConfiguration:
    """Create test configuration with immediate (no delay) summarization."""
    return MemoryConfiguration(
        available=True,
        default_enabled=True,
        summarization_delay_seconds=0,  # Immediate summarization
        require_project_discovery=False,  # Don't require project discovery in tests
    )


@pytest.fixture
def delayed_service(delayed_config: MemoryConfiguration) -> MemoryService:
    """Create service with mocks and delayed summarization."""
    repository_mock = AsyncMock()
    capture_buffer_mock = AsyncMock()
    tool_collector_mock = AsyncMock()

    return MemoryService(
        config=delayed_config,
        repository=repository_mock,
        capture_buffer=capture_buffer_mock,
        tool_event_collector=tool_collector_mock,
    )


@pytest.fixture
def immediate_service(immediate_config: MemoryConfiguration) -> MemoryService:
    """Create service with mocks and immediate summarization."""
    repository_mock = AsyncMock()
    capture_buffer_mock = AsyncMock()
    tool_collector_mock = AsyncMock()

    return MemoryService(
        config=immediate_config,
        repository=repository_mock,
        capture_buffer=capture_buffer_mock,
        tool_event_collector=tool_collector_mock,
    )


@pytest.mark.asyncio
class TestDelayedSummarization:
    """Test delayed session summarization feature."""

    async def test_immediate_summarization_when_delay_zero(
        self, immediate_service: MemoryService
    ):
        """Test that delay=0 provides immediate summarization."""
        # Enable session
        assert await immediate_service.enable_for_session("test_session", "test_user")

        # Mark complete - should queue immediately
        assert await immediate_service.mark_session_complete("test_session")

        # Should be queued immediately
        session_id = await immediate_service.get_pending_analysis_session()
        assert session_id == "test_session"

    async def test_delayed_summarization_with_default_delay(
        self, delayed_service: MemoryService
    ):
        """Test delayed summarization with default 2-second delay."""
        # Enable session
        assert await delayed_service.enable_for_session("test_session", "test_user")

        # Mark complete - should schedule background task
        assert await delayed_service.mark_session_complete("test_session")

        # Task should be scheduled but not yet executed
        state = await delayed_service.get_session_state("test_session")
        assert state is not None
        assert state.summary_task is not None
        assert state.summary_task.done() is False

        # No session should be available for analysis yet
        session_id = await delayed_service.get_pending_analysis_session()
        assert session_id is None

        # Wait for delay + small buffer
        await asyncio.sleep(2.5)

        # Now session should be available
        session_id = await delayed_service.get_pending_analysis_session()
        assert session_id == "test_session"

    async def test_session_resume_cancels_pending_summary(
        self, delayed_service: MemoryService
    ):
        """Test that session resume cancels pending summary tasks."""
        # Enable session
        assert await delayed_service.enable_for_session("test_session", "test_user")

        # Mark complete - schedules task
        assert await delayed_service.mark_session_complete("test_session")

        # Verify task is scheduled
        state = await delayed_service.get_session_state("test_session")
        assert state is not None
        assert state.summary_task is not None
        original_task = state.summary_task

        # Disable session (simulates session end) - this cancels the task
        await delayed_service.disable_for_session("test_session")

        # Wait for the task to complete its cancellation
        with contextlib.suppress(asyncio.CancelledError):
            await original_task

        # Re-enable session (simulates resume)
        assert await delayed_service.enable_for_session("test_session", "test_user")

        # Task should be cancelled
        assert original_task.cancelled()

    async def test_multiple_completion_calls_only_create_one_task(
        self, delayed_service: MemoryService
    ):
        """Test that multiple completion calls only create one background task."""
        # Enable session
        assert await delayed_service.enable_for_session("test_session", "test_user")

        # Call mark_session_complete multiple times
        assert await delayed_service.mark_session_complete("test_session")
        result = await delayed_service.mark_session_complete("test_session")
        assert result is False  # Second call should return False

        # Should only have one task
        state = await delayed_service.get_session_state("test_session")
        assert state is not None
        assert state.summary_task is not None

        # Original task should still be running
        assert state.summary_task.done() is False

    async def test_session_state_cleanup_on_analysis_complete(
        self, delayed_service: MemoryService
    ):
        """Test that session state is cleaned up when analysis completes."""
        # Enable session
        assert await delayed_service.enable_for_session("test_session", "test_user")

        # Mark complete
        assert await delayed_service.mark_session_complete("test_session")

        # Complete analysis (simulating what AnalysisWorker does)
        await delayed_service.complete_analysis("test_session")

        # Session should be removed
        state = await delayed_service.get_session_state("test_session")
        assert state is None

    async def test_delayed_task_error_handling(self, delayed_service: MemoryService):
        """Test that delayed tasks handle exceptions gracefully."""
        # Enable session
        assert await delayed_service.enable_for_session("test_session", "test_user")

        # Mark complete
        assert await delayed_service.mark_session_complete("test_session")

        # Wait for task to complete
        state = await delayed_service.get_session_state("test_session")
        assert state is not None
        await state.summary_task

        # Task should complete without raising exceptions
        # (even though it would have failed to queue due to mocks)
