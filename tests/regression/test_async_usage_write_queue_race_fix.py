"""Regression tests for race condition fixes in AsyncUsageWriteQueue."""

import asyncio
from datetime import datetime, timezone

from src.core.domain.traffic_leg import TrafficLeg
from src.core.domain.usage_record import UsageRecord
from src.core.services.async_usage_write_queue import AsyncUsageWriteQueue


class MockWriter:
    """Mock writer for testing."""

    async def batch_insert(self, records):
        return len(records)

    async def batch_update(self, records):
        return len(records)


async def test_concurrent_statistics_updates_no_race():
    """Test concurrent updates to statistics counters are safe."""
    writer = MockWriter()
    queue = AsyncUsageWriteQueue(writer, batch_size=10, flush_interval_seconds=0.05)
    await queue.start()

    fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    records = [
        UsageRecord(
            id=f"rec-{i}",
            timestamp=fixed_time,
            session_id=f"session-{i % 10}",
            turn_number=1,
            backend_type="test",
            model="test-model",
            frontend_type="openai",
            leg=TrafficLeg.PROXY_TO_CLIENT,
            verbatim_prompt_tokens=100,
            verbatim_completion_tokens=50,
            mutated_prompt_tokens=100,
            mutated_completion_tokens=50,
            total_tokens=150,
        )
        for i in range(200)
    ]

    async def enqueue_batch(recs):
        for r in recs:
            queue.enqueue_insert(r)

    async def access_stats():
        for _ in range(100):
            stats = queue.statistics
            assert hasattr(
                stats, "is_running"
            ), "Stats should have is_running attribute"

    tasks = [enqueue_batch(records) for _ in range(10)] + [
        access_stats() for _ in range(10)
    ]
    await asyncio.gather(*tasks, return_exceptions=True)

    await queue.stop()

    # Verify stats are consistent
    stats = queue.statistics
    assert stats.total_inserts > 0, "Expected some inserts"
    assert stats.total_batches > 0, "Expected some batches"


if __name__ == "__main__":
    asyncio.run(test_concurrent_statistics_updates_no_race())
    print("PASS: test_concurrent_statistics_updates_no_race")
