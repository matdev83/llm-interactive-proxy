"""Repro script for memory leak in AsyncUsageWriteQueue._pending_records.

This script demonstrates that _pending_records can grow unbounded when:
1. Records are enqueued but background task never processes them
2. Records fail to write but are removed from queue
3. Records accumulate faster than they're processed
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime

from src.core.domain.traffic_leg import TrafficLeg
from src.core.domain.usage_record import UsageRecord
from src.core.services.async_usage_write_queue import AsyncUsageWriteQueue, IUsageRecordWriter


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
        await asyncio.sleep(1.0)  # Slow processing
        return len(records)

    async def batch_update(self, records: list[UsageRecord]) -> int:
        """Process slowly."""
        await asyncio.sleep(1.0)  # Slow processing
        return len(records)


async def test_unbounded_growth_with_failing_writer():
    """Test that _pending_records grows unbounded when writes fail."""
    print("=" * 80)
    print("Test 1: Unbounded growth with failing writer")
    print("=" * 80)

    writer = FailingWriter()
    queue = AsyncUsageWriteQueue(writer, batch_size=10, flush_interval_seconds=0.1)

    await queue.start()

    # Enqueue many records
    num_records = 1000
    print(f"Enqueuing {num_records} records...")

    for i in range(num_records):
        record = UsageRecord(
            id=f"record_{i}",
            timestamp=datetime.now(),
            session_id=f"session_{i % 10}",
            turn_number=i,
            backend_type="test",
            model="test-model",
            frontend_type="test",
            leg=TrafficLeg.CLIENT_TO_PROXY,
            verbatim_prompt_tokens=100,
            verbatim_completion_tokens=50,
        )
        queue.enqueue_insert(record)

    # Wait a bit for processing attempts
    await asyncio.sleep(2.0)

    # Check pending_records size
    pending_count = queue.pending_count
    print(f"Pending records count: {pending_count}")
    print(f"Expected: {num_records} (all records should still be pending)")
    print(f"Queue sizes: insert={queue.insert_queue_size}, update={queue.update_queue_size}")

    if pending_count >= num_records * 0.8:  # At least 80% still pending
        print("[CONFIRMED] _pending_records grew unbounded (most records still pending)")
    else:
        print("[NOT CONFIRMED] Some records were cleaned up")

    await queue.stop()


async def test_unbounded_growth_with_stopped_task():
    """Test that _pending_records grows unbounded when background task stops."""
    print("\n" + "=" * 80)
    print("Test 2: Unbounded growth when background task stops")
    print("=" * 80)

    writer = SlowWriter()
    queue = AsyncUsageWriteQueue(writer, batch_size=10, flush_interval_seconds=0.1)

    await queue.start()

    # Enqueue records
    num_records = 500
    print(f"Enqueuing {num_records} records...")

    for i in range(num_records):
        record = UsageRecord(
            id=f"record_{i}",
            timestamp=datetime.now(),
            session_id=f"session_{i % 10}",
            turn_number=i,
            backend_type="test",
            model="test-model",
            frontend_type="test",
            leg=TrafficLeg.CLIENT_TO_PROXY,
            verbatim_prompt_tokens=100,
            verbatim_completion_tokens=50,
        )
        queue.enqueue_insert(record)

    # Stop the queue immediately (simulating task failure)
    print("Stopping queue immediately (simulating task failure)...")
    await queue.stop(timeout=0.1)  # Short timeout to simulate failure

    # Check pending_records size
    pending_count = queue.pending_count
    print(f"Pending records count: {pending_count}")
    print(f"Expected: ~{num_records} (records should still be pending after stop)")

    if pending_count >= num_records * 0.9:  # Allow some processing
        print("[CONFIRMED] _pending_records grew unbounded (records remain after stop)")
    else:
        print("[NOT CONFIRMED] Records were cleaned up")


async def test_unbounded_growth_with_fast_enqueue():
    """Test that _pending_records grows unbounded when enqueuing faster than processing."""
    print("\n" + "=" * 80)
    print("Test 3: Unbounded growth with fast enqueue")
    print("=" * 80)

    writer = SlowWriter()
    queue = AsyncUsageWriteQueue(writer, batch_size=10, flush_interval_seconds=1.0)

    await queue.start()

    # Enqueue records very fast
    num_records = 2000
    print(f"Enqueuing {num_records} records very fast...")

    for i in range(num_records):
        record = UsageRecord(
            id=f"record_{i}",
            timestamp=datetime.now(),
            session_id=f"session_{i % 10}",
            turn_number=i,
            backend_type="test",
            model="test-model",
            frontend_type="test",
            leg=TrafficLeg.CLIENT_TO_PROXY,
            verbatim_prompt_tokens=100,
            verbatim_completion_tokens=50,
        )
        queue.enqueue_insert(record)

    # Check immediately (before processing can catch up)
    pending_count_before = queue.pending_count
    print(f"Pending records count (immediate): {pending_count_before}")

    # Wait a bit
    await asyncio.sleep(2.0)

    # Check again
    pending_count_after = queue.pending_count
    print(f"Pending records count (after 2s): {pending_count_after}")

    if pending_count_before >= num_records * 0.9:
        print("[CONFIRMED] _pending_records can grow very large")
        if pending_count_after >= num_records * 0.5:
            print("  WARNING: Records are not being cleaned up fast enough")
    else:
        print("[NOT CONFIRMED] Records are being cleaned up")

    await queue.stop()


async def test_fix_verification():
    """Verify that the fix limits _pending_records growth."""
    print("\n" + "=" * 80)
    print("Test 4: Fix verification - pending_records should be limited")
    print("=" * 80)

    writer = SlowWriter()
    # Use small max_pending_records to verify limit enforcement
    queue = AsyncUsageWriteQueue(
        writer, batch_size=10, flush_interval_seconds=1.0, max_pending_records=100
    )

    await queue.start()

    # Enqueue many records
    num_records = 500
    print(f"Enqueuing {num_records} records with max_pending_records=100...")

    for i in range(num_records):
        record = UsageRecord(
            id=f"record_{i}",
            timestamp=datetime.now(),
            session_id=f"session_{i % 10}",
            turn_number=i,
            backend_type="test",
            model="test-model",
            frontend_type="test",
            leg=TrafficLeg.CLIENT_TO_PROXY,
            verbatim_prompt_tokens=100,
            verbatim_completion_tokens=50,
        )
        queue.enqueue_insert(record)

    # Check pending_records size immediately
    pending_count = queue.pending_count
    print(f"Pending records count: {pending_count}")
    print(f"Expected: <= 100 (limited by max_pending_records)")

    if pending_count <= 100:
        print("[FIX VERIFIED] _pending_records is properly limited")
    else:
        print("[FIX FAILED] _pending_records exceeded limit")

    await queue.stop()


async def main():
    """Run all tests."""
    print("Memory Leak Repro: AsyncUsageWriteQueue._pending_records")
    print("=" * 80)

    await test_unbounded_growth_with_failing_writer()
    await test_unbounded_growth_with_stopped_task()
    await test_unbounded_growth_with_fast_enqueue()
    await test_fix_verification()

    print("\n" + "=" * 80)
    print("Summary: Tests 1-3 demonstrate the leak (if present), Test 4 verifies the fix.")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
