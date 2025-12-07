"""Unit tests for SessionCompletionDetector."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

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

    def test_record_activity_tracks_session(self) -> None:
        """Test that activity is recorded."""
        service = create_mock_memory_service()
        config = create_mock_config()
        detector = SessionCompletionDetector(service, config)

        detector.record_activity("session-1")

        assert "session-1" in detector._last_activity

    def test_record_activity_ignores_completed_sessions(self) -> None:
        """Test that completed sessions don't get activity recorded."""
        service = create_mock_memory_service()
        config = create_mock_config()
        detector = SessionCompletionDetector(service, config)

        detector._completed_sessions.add("session-1")
        detector.record_activity("session-1")

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
