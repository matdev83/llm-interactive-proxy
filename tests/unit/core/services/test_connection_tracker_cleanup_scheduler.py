"""Tests for ConnectionTrackerCleanupScheduler."""

import asyncio
import time
from unittest.mock import MagicMock

import pytest
from src.core.services.connection_tracker_cleanup_scheduler import (
    ConnectionTrackerCleanupScheduler,
)


class TestConnectionTrackerCleanupScheduler:
    """Tests for the connection tracker cleanup scheduler."""

    def test_scheduler_initialization(self) -> None:
        """Test scheduler is initialized correctly."""
        mock_tracker = MagicMock()
        scheduler = ConnectionTrackerCleanupScheduler(
            activity_tracker=mock_tracker,
            cleanup_interval_seconds=150,
        )

        assert scheduler._activity_tracker is mock_tracker
        assert scheduler._cleanup_interval == 150
        assert not scheduler.is_running
        assert scheduler._cleanup_task is None

    @pytest.mark.asyncio
    async def test_start_stop_cycle(self) -> None:
        """Test starting and stopping the scheduler."""
        mock_tracker = MagicMock()
        mock_tracker.cleanup_stale_connections.return_value = 5

        scheduler = ConnectionTrackerCleanupScheduler(
            activity_tracker=mock_tracker,
            cleanup_interval_seconds=1,  # Short interval for testing
        )

        # Initially not running
        assert not scheduler.is_running

        # Start scheduler
        await scheduler.start()
        assert scheduler.is_running
        assert scheduler._cleanup_task is not None
        assert not scheduler._cleanup_task.done()

        # Wait for at least one cleanup cycle
        await asyncio.sleep(1.5)

        # Verify cleanup was called
        mock_tracker.cleanup_stale_connections.assert_called()

        # Stop scheduler
        await scheduler.stop()
        assert not scheduler.is_running
        assert scheduler._cleanup_task is None

    @pytest.mark.asyncio
    async def test_start_when_already_running(self) -> None:
        """Test that starting an already running scheduler is a no-op."""
        mock_tracker = MagicMock()
        scheduler = ConnectionTrackerCleanupScheduler(
            activity_tracker=mock_tracker,
            cleanup_interval_seconds=60,
        )

        await scheduler.start()
        task = scheduler._cleanup_task

        # Try to start again
        await scheduler.start()

        # Should still have the same task
        assert scheduler._cleanup_task is task

        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self) -> None:
        """Test that stopping a non-running scheduler is a no-op."""
        mock_tracker = MagicMock()
        scheduler = ConnectionTrackerCleanupScheduler(
            activity_tracker=mock_tracker,
            cleanup_interval_seconds=60,
        )

        # Should not raise any exception
        await scheduler.stop()
        assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_cleanup_with_connections_removed(self) -> None:
        """Test cleanup process when connections are actually removed."""
        mock_tracker = MagicMock()
        mock_tracker.cleanup_stale_connections.return_value = 3

        scheduler = ConnectionTrackerCleanupScheduler(
            activity_tracker=mock_tracker,
            cleanup_interval_seconds=1,
        )

        await scheduler.start()
        await asyncio.sleep(1.5)  # Wait for cleanup cycle
        await scheduler.stop()

        # Verify cleanup was called
        mock_tracker.cleanup_stale_connections.assert_called()

    @pytest.mark.asyncio
    async def test_cleanup_with_no_connections_removed(self) -> None:
        """Test cleanup process when no connections are removed."""
        mock_tracker = MagicMock()
        mock_tracker.cleanup_stale_connections.return_value = 0

        scheduler = ConnectionTrackerCleanupScheduler(
            activity_tracker=mock_tracker,
            cleanup_interval_seconds=1,
        )

        await scheduler.start()
        await asyncio.sleep(1.5)  # Wait for cleanup cycle
        await scheduler.stop()

        # Verify cleanup was called
        mock_tracker.cleanup_stale_connections.assert_called()

    @pytest.mark.asyncio
    async def test_cleanup_handles_exceptions_gracefully(self) -> None:
        """Test that cleanup exceptions don't stop the scheduler."""
        mock_tracker = MagicMock()
        mock_tracker.cleanup_stale_connections.side_effect = [
            Exception("Test error"),
            2,  # Second call succeeds
        ]

        scheduler = ConnectionTrackerCleanupScheduler(
            activity_tracker=mock_tracker,
            cleanup_interval_seconds=1,
        )

        await scheduler.start()
        await asyncio.sleep(2.5)  # Wait for multiple cleanup cycles
        await scheduler.stop()

        # Verify cleanup was called multiple times despite exception
        assert mock_tracker.cleanup_stale_connections.call_count >= 2

    @pytest.mark.asyncio
    async def test_stop_with_timeout(self) -> None:
        """Test stopping scheduler when cleanup task doesn't finish quickly."""
        mock_tracker = MagicMock()

        # Create a slow cleanup task
        async def slow_cleanup():
            await asyncio.sleep(35)  # Longer than 30s timeout
            return 1

        mock_tracker.cleanup_stale_connections = slow_cleanup

        scheduler = ConnectionTrackerCleanupScheduler(
            activity_tracker=mock_tracker,
            cleanup_interval_seconds=1,
        )

        await scheduler.start()
        await asyncio.sleep(0.5)  # Let cleanup start

        # Stop should timeout and cancel the task
        await scheduler.stop()
        assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_shutdown_signal_handling(self) -> None:
        """Test that scheduler responds to shutdown signal promptly."""
        mock_tracker = MagicMock()
        mock_tracker.cleanup_stale_connections.return_value = 1

        scheduler = ConnectionTrackerCleanupScheduler(
            activity_tracker=mock_tracker,
            cleanup_interval_seconds=30,  # Long interval
        )

        await scheduler.start()

        # Should stop quickly despite long interval
        start_time = time.time()
        await scheduler.stop()
        elapsed = time.time() - start_time

        assert elapsed < 5  # Should stop immediately, not wait for interval
        assert not scheduler.is_running
