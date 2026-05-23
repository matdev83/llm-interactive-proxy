"""Unit tests for SessionCompletionDetector."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.core.memory.completion_detector import SessionCompletionDetector


def create_mock_memory_service(
    *,
    available: bool = True,
    enabled: bool = True,
) -> MagicMock:
    """Create a mock memory service."""
    service = MagicMock()
    service.is_available.return_value = available
    service.is_enabled_for_session = AsyncMock(return_value=enabled)
    service.mark_session_complete = AsyncMock(return_value=True)
    return service


def create_mock_config(timeout_minutes: int = 30) -> MagicMock:
    """Create a mock memory config."""
    config = MagicMock()
    config.session_timeout_minutes = timeout_minutes
    return config


class TestSessionCompletionDetector:
    """Tests for SessionCompletionDetector."""

    @pytest.mark.asyncio
    async def test_record_activity_tracks_session(self) -> None:
        """Test that activity is recorded."""
        service = create_mock_memory_service()
        config = create_mock_config()
        detector = SessionCompletionDetector(service, config)

        await detector.record_activity("session-1")

        assert "session-1" in detector._last_activity

    @pytest.mark.asyncio
    async def test_record_activity_ignores_completed_sessions(self) -> None:
        """Test that completed sessions don't get activity recorded."""
        service = create_mock_memory_service()
        config = create_mock_config()
        detector = SessionCompletionDetector(service, config)

        detector._completed_sessions.add("session-1")
        await detector.record_activity("session-1")

        assert "session-1" not in detector._last_activity

    @pytest.mark.asyncio
    async def test_on_session_close_skips_when_unavailable(self) -> None:
        """Test that close is skipped when memory unavailable."""
        service = create_mock_memory_service(available=False)
        config = create_mock_config()
        detector = SessionCompletionDetector(service, config)

        await detector.on_session_close("session-1")

        service.mark_session_complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_session_close_skips_when_disabled(self) -> None:
        """Test that close is skipped when session not enabled."""
        service = create_mock_memory_service(enabled=False)
        config = create_mock_config()
        detector = SessionCompletionDetector(service, config)

        await detector.on_session_close("session-1")

        service.mark_session_complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_session_close_marks_complete(self) -> None:
        """Test that close marks session complete."""
        service = create_mock_memory_service()
        config = create_mock_config()
        detector = SessionCompletionDetector(service, config)

        await detector.on_session_close(
            "session-1",
            backend_model="openai:gpt-4o",
            branch="main",
            head_sha="abc123",
        )

        service.mark_session_complete.assert_called_once_with(
            "session-1",
            backend_model="openai:gpt-4o",
            branch="main",
            head_sha="abc123",
        )

    @pytest.mark.asyncio
    async def test_on_session_close_only_once(self) -> None:
        """Test that close only happens once per session."""
        service = create_mock_memory_service()
        config = create_mock_config()
        detector = SessionCompletionDetector(service, config)

        await detector.on_session_close("session-1")
        await detector.on_session_close("session-1")

        assert service.mark_session_complete.call_count == 1

    @pytest.mark.asyncio
    async def test_check_timeouts_detects_expired(self) -> None:
        """Test that timed-out sessions are detected."""
        service = create_mock_memory_service()
        config = create_mock_config(timeout_minutes=1)  # 1 minute timeout
        detector = SessionCompletionDetector(service, config)

        # Record activity 2 minutes ago
        base_time = 1000.0
        with patch("time.time", return_value=base_time):
            detector._last_activity["session-1"] = time.time() - 120
            await detector._check_timeouts()

        service.mark_session_complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_timeouts_ignores_active(self) -> None:
        """Test that active sessions are not timed out."""
        service = create_mock_memory_service()
        config = create_mock_config(timeout_minutes=30)
        detector = SessionCompletionDetector(service, config)

        # Record recent activity
        base_time = 1000.0
        with patch("time.time", return_value=base_time):
            detector._last_activity["session-1"] = time.time() - 60
            await detector._check_timeouts()

        service.mark_session_complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_stop_timeout_checker(self) -> None:
        """Test starting and stopping the timeout checker."""
        service = create_mock_memory_service()
        config = create_mock_config()
        detector = SessionCompletionDetector(service, config)

        await detector.start_timeout_checker()
        assert detector._running is True
        assert detector._cleanup_task is not None

        await detector.stop_timeout_checker()
        assert detector._running is False
        assert detector._cleanup_task is None

    def test_clear_session_removes_tracking(self) -> None:
        """Test that clear removes all session tracking."""
        service = create_mock_memory_service()
        config = create_mock_config()
        detector = SessionCompletionDetector(service, config)

        base_time = 1000.0
        with patch("time.time", return_value=base_time):
            detector._last_activity["session-1"] = time.time()
        detector._completed_sessions.add("session-1")

        detector.clear_session("session-1")

        assert "session-1" not in detector._last_activity
        assert "session-1" not in detector._completed_sessions

    @pytest.mark.asyncio
    async def test_double_start_is_safe(self) -> None:
        """Test that double start doesn't create multiple tasks."""
        service = create_mock_memory_service()
        config = create_mock_config()
        detector = SessionCompletionDetector(service, config)

        await detector.start_timeout_checker()
        task1 = detector._cleanup_task

        await detector.start_timeout_checker()
        task2 = detector._cleanup_task

        assert task1 is task2

        await detector.stop_timeout_checker()

    @pytest.mark.asyncio
    async def test_concurrent_activity_and_completion(self) -> None:
        """Test that concurrent activity recording and completion are safe.

        This verifies that lock prevents races between:
        1. record_activity checking _completed_sessions
        2. _complete_session adding to _completed_sessions

        Without a lock, a race could allow:
        - Activity recorded after session is marked complete
        - Session completed multiple times
        """
        service = create_mock_memory_service()
        config = create_mock_config()
        detector = SessionCompletionDetector(service, config)

        session_id = "test-session-concurrent"

        # Launch concurrent activity recordings and completions
        tasks = [detector.record_activity(session_id) for _ in range(100)]
        # Also try to complete session concurrently
        completion_tasks = [
            detector.on_session_close(session_id)
            for _ in range(10)  # Try to complete 10 times
        ]

        # All should complete without errors
        await asyncio.gather(*tasks, *completion_tasks, return_exceptions=True)

        # Session should be marked complete exactly once
        assert session_id in detector._completed_sessions
        assert service.mark_session_complete.call_count == 1

    @pytest.mark.asyncio
    async def test_concurrent_different_sessions(self) -> None:
        """Test that concurrent requests for different sessions work correctly.

        This ensures lock doesn't cause unnecessary contention when
        requests are for different sessions (they still need the lock
        to prevent check-then-act race, but we verify they don't interfere).
        """
        service = create_mock_memory_service()
        config = create_mock_config()
        detector = SessionCompletionDetector(service, config)

        num_sessions = 20
        activities_per_session = 10

        # Create activity for multiple sessions concurrently
        tasks = []
        for session_idx in range(num_sessions):
            session_id = f"test-session-{session_idx}"
            for _ in range(activities_per_session):
                tasks.append(detector.record_activity(session_id))

        await asyncio.gather(*tasks)

        # All sessions should be tracked
        assert len(detector._last_activity) == num_sessions

        # Each session should have been recorded once
        for session_idx in range(num_sessions):
            session_id = f"test-session-{session_idx}"
            assert session_id in detector._last_activity
