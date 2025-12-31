"""Tests for AsyncUsageWriteQueue."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from freezegun import freeze_time
from src.core.domain.traffic_leg import TrafficLeg
from src.core.domain.usage_record import UsageRecord
from src.core.services.async_usage_write_queue import AsyncUsageWriteQueue

from tests.unit.fixtures.markers import real_time
from tests.utils.fake_clock import FakeClockContext


def create_test_record(record_id: str | None = None) -> UsageRecord:
    """Create a test usage record."""
    with freeze_time("2024-01-01 12:00:00"):
        return UsageRecord(
            id=record_id or str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            session_id="test-session",
            turn_number=1,
            backend_type="openai",
            model="gpt-4",
            frontend_type="openai",
            leg=TrafficLeg.CLIENT_TO_PROXY,
            verbatim_prompt_tokens=100,
            total_tokens=100,
        )


def create_test_record_fast(record_id: str | None = None) -> UsageRecord:
    """Create a test usage record without freeze_time for performance.

    This version creates the datetime directly without using freeze_time,
    which is significantly faster when creating many records.
    """
    return UsageRecord(
        id=record_id or str(uuid.uuid4()),
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        session_id="test-session",
        turn_number=1,
        backend_type="openai",
        model="gpt-4",
        frontend_type="openai",
        leg=TrafficLeg.CLIENT_TO_PROXY,
        verbatim_prompt_tokens=100,
        total_tokens=100,
    )


@pytest.mark.asyncio
class TestAsyncUsageWriteQueueBasic:
    """Basic tests for AsyncUsageWriteQueue."""

    @pytest.fixture
    def mock_writer(self):
        """Create a mock writer."""
        writer = MagicMock()
        writer.batch_insert = AsyncMock(return_value=5)
        writer.batch_update = AsyncMock(return_value=3)
        return writer

    async def test_init(self, mock_writer):
        """Test queue initialization."""
        queue = AsyncUsageWriteQueue(
            writer=mock_writer,
            batch_size=50,
            flush_interval_seconds=10.0,
            max_queue_size=5000,
        )

        assert queue._batch_size == 50
        assert queue._flush_interval == 10.0
        assert queue._max_queue_size == 5000
        assert queue._is_running is False

    async def test_enqueue_insert_before_start(self, mock_writer):
        """Test that enqueue works before starting the queue."""
        queue = AsyncUsageWriteQueue(writer=mock_writer)

        record = create_test_record()
        result = queue.enqueue_insert(record)

        assert result is True
        assert queue.insert_queue_size == 1

    async def test_enqueue_update_before_start(self, mock_writer):
        """Test that update enqueue works before starting the queue."""
        queue = AsyncUsageWriteQueue(writer=mock_writer)

        record = create_test_record()
        result = queue.enqueue_update(record)

        assert result is True
        assert queue.update_queue_size == 1

    async def test_enqueue_insert_full_queue(self, mock_writer):
        """Test enqueue returns False when queue is full."""
        queue = AsyncUsageWriteQueue(
            writer=mock_writer,
            max_queue_size=2,
        )

        # Fill the queue
        queue.enqueue_insert(create_test_record())
        queue.enqueue_insert(create_test_record())

        # This one should fail
        result = queue.enqueue_insert(create_test_record())
        assert result is False

    async def test_statistics(self, mock_writer):
        """Test statistics property."""
        queue = AsyncUsageWriteQueue(writer=mock_writer)

        queue.enqueue_insert(create_test_record())
        queue.enqueue_update(create_test_record())

        stats = queue.statistics

        assert stats.is_running is False
        assert stats.insert_queue_size == 1
        assert stats.update_queue_size == 1
        assert stats.batch_size == 100
        assert stats.flush_interval_seconds == 5.0


@pytest.mark.asyncio
class TestAsyncUsageWriteQueueAsync:
    """Async tests for AsyncUsageWriteQueue."""

    @pytest.fixture
    def mock_writer(self):
        """Create a mock writer."""
        writer = MagicMock()
        writer.batch_insert = AsyncMock(return_value=5)
        writer.batch_update = AsyncMock(return_value=3)
        return writer

    async def test_start_stop(self, mock_writer):
        """Test starting and stopping the queue."""
        queue = AsyncUsageWriteQueue(
            writer=mock_writer,
            flush_interval_seconds=0.1,
        )

        await queue.start()
        assert queue._is_running is True
        assert queue._background_task is not None

        await queue.stop()
        assert queue._is_running is False

    async def test_get_pending_record(self, mock_writer):
        """Test getting a pending record from cache."""
        queue = AsyncUsageWriteQueue(writer=mock_writer)

        record = create_test_record("test-id-123")
        queue.enqueue_insert(record)

        # Pending cache is updated synchronously now
        pending = await queue.get_pending_record("test-id-123")
        assert pending is not None
        assert pending.id == "test-id-123"

    async def test_get_pending_record_not_found(self, mock_writer):
        """Test getting a non-existent pending record."""
        queue = AsyncUsageWriteQueue(writer=mock_writer)

        pending = await queue.get_pending_record("nonexistent")
        assert pending is None

    async def test_flush_batches(self, mock_writer):
        """Test that batches are flushed."""
        queue = AsyncUsageWriteQueue(
            writer=mock_writer,
            batch_size=5,
            flush_interval_seconds=0.05,
        )

        # Add some records
        for _ in range(3):
            queue.enqueue_insert(create_test_record())

        await queue.start()

        # Wait for flush
        async with FakeClockContext() as clock:
            sleep_task = asyncio.create_task(asyncio.sleep(0.1))
            clock.advance(0.1)
            await sleep_task

        await queue.stop()

        # Verify batch_insert was called
        assert mock_writer.batch_insert.called

    async def test_drain_on_stop(self, mock_writer):
        """Test that queues are drained on stop."""
        queue = AsyncUsageWriteQueue(
            writer=mock_writer,
            batch_size=100,  # Large batch size
            flush_interval_seconds=10.0,  # Long interval
        )

        # Add records
        for _ in range(5):
            queue.enqueue_insert(create_test_record())

        await queue.start()
        await queue.stop()

        # All records should have been flushed
        assert queue.insert_queue_size == 0

    async def test_concurrent_enqueue(self, mock_writer):
        """Test concurrent enqueue operations."""
        queue = AsyncUsageWriteQueue(
            writer=mock_writer,
            max_queue_size=1000,
        )

        # Concurrently enqueue many records
        async def enqueue_batch(count: int):
            for _ in range(count):
                queue.enqueue_insert(create_test_record_fast())

        # Run multiple concurrent tasks
        tasks = [enqueue_batch(50) for _ in range(10)]
        await asyncio.gather(*tasks)

        # Should have 500 records
        assert queue.insert_queue_size == 500


@pytest.mark.asyncio
class TestAsyncUsageWriteQueuePerformance:
    """Performance-focused tests for AsyncUsageWriteQueue."""

    @real_time(reason="Measures enqueue performance using real perf_counter timing.")
    async def test_enqueue_is_nonblocking(self):
        """Test that enqueue does not block."""
        mock_writer = MagicMock()
        mock_writer.batch_insert = AsyncMock(return_value=100)
        mock_writer.batch_update = AsyncMock(return_value=100)

        queue = AsyncUsageWriteQueue(writer=mock_writer)

        import time

        # Use fast version to avoid repeated freeze_time context overhead
        records = [create_test_record_fast(f"record-{i}") for i in range(1000)]

        # Enqueue 1000 records and measure time
        start = time.perf_counter()
        for record in records:
            queue.enqueue_insert(record)
        elapsed = time.perf_counter() - start

        # Should be very fast - less than 100ms for 1000 enqueues
        assert elapsed < 0.1, f"Enqueue took {elapsed:.3f}s, expected < 0.1s"

    async def test_batch_size_respected(self):
        """Test that batch size is respected during flush."""
        inserted_batches = []

        async def mock_insert(records):
            inserted_batches.append(len(records))
            return len(records)

        mock_writer = MagicMock()
        mock_writer.batch_insert = mock_insert
        mock_writer.batch_update = AsyncMock(return_value=0)

        queue = AsyncUsageWriteQueue(
            writer=mock_writer,
            batch_size=10,
            flush_interval_seconds=0.01,
        )

        # Add 25 records
        # Use create_test_record_fast() to avoid freeze_time overhead
        for _ in range(25):
            queue.enqueue_insert(create_test_record_fast())

        await queue.start()
        async with FakeClockContext() as clock:
            sleep_task = asyncio.create_task(asyncio.sleep(0.1))
            clock.advance(0.1)  # Wait for flushes
            await sleep_task
        await queue.stop()

        # Should have processed in batches of 10 or less
        assert all(size <= 10 for size in inserted_batches)
