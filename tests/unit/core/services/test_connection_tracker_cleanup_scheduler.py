"""Tests for ConnectionTrackerCleanupScheduler."""

import asyncio
import time
from unittest.mock import MagicMock

import pytest
from src.core.services.connection_tracker_cleanup_scheduler import (
    ConnectionTrackerCleanupScheduler,
)

from tests.utils.fake_clock import FakeClockContext


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
            cleanup_interval_seconds=0.1,
        )

        # Initially not running
        assert not scheduler.is_running

        # Use fake clock to control time progression
        async with FakeClockContext() as clock:
            # Start scheduler
            await scheduler.start()
            assert scheduler.is_running
            assert scheduler._cleanup_task is not None
            assert not scheduler._cleanup_task.done()

            # Advance clock to trigger at least one cleanup cycle
            clock.advance(0.15)

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
            cleanup_interval_seconds=0.1,
        )

        async with FakeClockContext() as clock:
            await scheduler.start()
            clock.advance(0.15)
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
            cleanup_interval_seconds=0.1,
        )

        async with FakeClockContext() as clock:
            await scheduler.start()
            clock.advance(0.15)
            await scheduler.stop()

        # Verify cleanup was called
        mock_tracker.cleanup_stale_connections.assert_called()

    @pytest.mark.asyncio
    async def test_cleanup_handles_exceptions_gracefully(self) -> None:
        """Test that cleanup exceptions don't stop the scheduler."""
        mock_tracker = MagicMock()
        mock_tracker.cleanup_stale_connections.side_effect = [
            Exception("Test error"),
            2,
        ]

        scheduler = ConnectionTrackerCleanupScheduler(
            activity_tracker=mock_tracker,
            cleanup_interval_seconds=0.1,
        )

        async with FakeClockContext() as clock:
            await scheduler.start()
            clock.advance(0.15)  # Advance time to allow 2 cleanup cycles
            await scheduler.stop()

        assert mock_tracker.cleanup_stale_connections.call_count >= 2

    @pytest.mark.asyncio
    async def test_stop_with_timeout(self) -> None:
        """Test stopping scheduler when cleanup task doesn't finish quickly."""
        mock_tracker = MagicMock()

        async def slow_cleanup():
            # Use fake clock for deterministic time simulation
            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.4))
                clock.advance(0.4)
                await sleep_task
            return 1

        mock_tracker.cleanup_stale_connections = slow_cleanup

        scheduler = ConnectionTrackerCleanupScheduler(
            activity_tracker=mock_tracker,
            cleanup_interval_seconds=0.1,
        )

        async with FakeClockContext() as clock:
            await scheduler.start()
            # Advance clock to trigger cleanup cycle
            clock.advance(0.1)
            # Stop scheduler (should handle slow cleanup gracefully)
            await scheduler.stop()
            # Advance clock to allow slow cleanup to complete
            clock.advance(0.4)
        assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_shutdown_signal_handling(self) -> None:
        """Test that scheduler responds to shutdown signal promptly."""
        mock_tracker = MagicMock()
        mock_tracker.cleanup_stale_connections.return_value = 1

        scheduler = ConnectionTrackerCleanupScheduler(
            activity_tracker=mock_tracker,
            cleanup_interval_seconds=10,
        )

        await scheduler.start()

        start_time = time.time()
        await scheduler.stop()
        elapsed = time.time() - start_time

        assert elapsed < 1
        assert not scheduler.is_running
