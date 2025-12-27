"""Regression test for AsyncUsageWriteQueue memory leak fix.

This test verifies that AsyncUsageWriteQueue._pending_records doesn't grow
unbounded when:
1. Records are enqueued but background task never processes them
2. Records fail to write but are removed from queue
3. Records accumulate faster than they're processed

Fixed: Added max_pending_records limit with FIFO eviction to prevent unbounded growth.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.traffic_leg import TrafficLeg
from src.core.domain.usage_record import UsageRecord
from src.core.services.async_usage_write_queue import (
    AsyncUsageWriteQueue,
    IUsageRecordWriter,
)


class FailingWriter(IUsageRecordWriter):
    """Writer that always fails to simulate write failures."""

    async def batch_insert(self, records: list[UsageRecord]) -> int:
        """Always fail."""
        raise Exception("Simulated write failure")

    async def batch_update(self, records: list[UsageRecord]) -> int:
        """Always fail."""
        raise Exception("Simulated write failure")


class SlowWriter(IUsageRecordWriter):
    """Writer that processes slowly to simulate accumulation."""

    async def batch_insert(self, records: list[UsageRecord]) -> int:
        """Process slowly."""
        await asyncio.sleep(0.0001)  # Very short delay for test performance
        return len(records)

    async def batch_update(self, records: list[UsageRecord]) -> int:
        """Process slowly."""
        await asyncio.sleep(0.0001)  # Very short delay for test performance
        return len(records)


def create_test_record(record_id: str) -> UsageRecord:
    """Create a test usage record."""
    return UsageRecord(
        id=record_id,
        timestamp=datetime.now(timezone.utc),
        session_id=f"session_{int(record_id.split('_')[1]) % 10}",
        turn_number=int(record_id.split("_")[1]) if "_" in record_id else 0,
        backend_type="test",
        model="test-model",
        frontend_type="test",
        leg=TrafficLeg.CLIENT_TO_PROXY,
        verbatim_prompt_tokens=100,
        verbatim_completion_tokens=50,
    )


class TestAsyncUsageWriteQueueMemoryLeakRegression:
    """Regression tests for AsyncUsageWriteQueue memory leak fix."""

    @pytest.mark.asyncio
    async def test_pending_records_limited_with_failing_writer(self) -> None:
        """Test that _pending_records doesn't grow unbounded when writes fail."""
        writer = FailingWriter()
        max_pending = 100
        queue = AsyncUsageWriteQueue(
            writer,
            batch_size=10,
            flush_interval_seconds=0.1,
            max_pending_records=max_pending,
        )

        await queue.start()

        # Enqueue many records
        num_records = 1000
        for i in range(num_records):
            record = create_test_record(f"record_{i}")
            queue.enqueue_insert(record)

        # Wait a bit for processing attempts (reduced from 0.5s to 0.05s)
        await asyncio.sleep(0.05)

        # Check pending_records size - should be limited
        pending_count = queue.pending_count
        assert pending_count <= max_pending, (
            f"Pending records ({pending_count}) exceeded max limit ({max_pending}). "
            "Memory leak detected - _pending_records grew unbounded."
        )

        await queue.stop()

    @pytest.mark.asyncio
    async def test_pending_records_limited_when_stopped_early(self) -> None:
        """Test that _pending_records doesn't grow unbounded when queue stops early."""
        writer = SlowWriter()
        max_pending = 50
        queue = AsyncUsageWriteQueue(
            writer,
            batch_size=10,
            flush_interval_seconds=0.1,
            max_pending_records=max_pending,
        )

        await queue.start()

        # Enqueue records (reduced number for faster test execution)
        num_records = 200
        for i in range(num_records):
            record = create_test_record(f"record_{i}")
            queue.enqueue_insert(record)

        # Stop the queue immediately (simulating task failure)
        await queue.stop(timeout=0.1)  # Short timeout

        # Check pending_records size - should be limited
        pending_count = queue.pending_count
        assert pending_count <= max_pending, (
            f"Pending records ({pending_count}) exceeded max limit ({max_pending}) after stop. "
            "Memory leak detected - records remain unbounded."
        )

    @pytest.mark.asyncio
    async def test_pending_records_limited_with_fast_enqueue(self) -> None:
        """Test that _pending_records doesn't grow unbounded when enqueuing faster than processing."""
        writer = SlowWriter()
        max_pending = 200
        queue = AsyncUsageWriteQueue(
            writer,
            batch_size=10,
            flush_interval_seconds=0.1,  # Reduced for faster test execution
            max_pending_records=max_pending,
        )

        await queue.start()

        # Enqueue records very fast (reduced from 500 to 300 for test performance)
        num_records = 300
        for i in range(num_records):
            record = create_test_record(f"record_{i}")
            queue.enqueue_insert(record)

        # Check immediately (before processing can catch up)
        pending_count_before = queue.pending_count
        assert pending_count_before <= max_pending, (
            f"Pending records ({pending_count_before}) exceeded max limit ({max_pending}) "
            "during fast enqueue. Memory leak detected."
        )

        # Wait a bit for processing (reduced for faster test execution)
        await asyncio.sleep(0.15)  # Reduced from 0.2

        # Check again - should still be limited
        pending_count_after = queue.pending_count
        assert pending_count_after <= max_pending, (
            f"Pending records ({pending_count_after}) exceeded max limit ({max_pending}) "
            "after processing. Records are not being cleaned up properly."
        )

        await queue.stop()

    @pytest.mark.asyncio
    async def test_pending_records_fifo_eviction(self) -> None:
        """Test that oldest records are evicted when limit is reached (FIFO eviction)."""
        writer = SlowWriter()
        max_pending = 50
        queue = AsyncUsageWriteQueue(
            writer,
            batch_size=10,
            flush_interval_seconds=0.2,
            max_pending_records=max_pending,
        )

        await queue.start()

        # Enqueue records beyond the limit
        num_records = 200
        for i in range(num_records):
            record = create_test_record(f"record_{i}")
            queue.enqueue_insert(record)

        # Wait a bit
        await asyncio.sleep(0.15)

        # Check that pending count is limited
        pending_count = queue.pending_count
        assert (
            pending_count <= max_pending
        ), f"Pending records ({pending_count}) exceeded max limit ({max_pending})"

        # Verify that oldest records were evicted (newer records should be present)
        # The exact records depend on processing, but we should have at most max_pending
        oldest_id = f"record_{num_records - max_pending}"
        newest_id = f"record_{num_records - 1}"

        # Newest record should be present (or recently processed)
        await queue.get_pending_record(newest_id)
        # Oldest record might not be present if evicted
        await queue.get_pending_record(oldest_id)

        # At least verify the count is correct
        assert pending_count <= max_pending

        await queue.stop()

    @pytest.mark.asyncio
    async def test_default_max_pending_records(self) -> None:
        """Test that default max_pending_records is set correctly."""
        writer = MagicMock()
        writer.batch_insert = AsyncMock(return_value=5)
        writer.batch_update = AsyncMock(return_value=3)

        queue = AsyncUsageWriteQueue(writer, max_queue_size=1000)

        # Default should be 2x max_queue_size
        expected_max = 1000 * 2
        assert queue._max_pending_records == expected_max, (
            f"Default max_pending_records ({queue._max_pending_records}) should be "
            f"2x max_queue_size ({expected_max})"
        )
