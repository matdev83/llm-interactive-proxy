"""Reproduce race condition in AsyncUsageWriteQueue statistics counters"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.services.async_usage_write_queue import AsyncUsageWriteQueue
from src.core.domain.usage_record import UsageRecord


class MockWriter:
    """Mock writer for testing."""

    async def batch_insert(self, records):
        return len(records)

    async def batch_update(self, records):
        return len(records)


async def test_concurrent_statistics_updates():
    """Test concurrent updates to statistics counters."""
    writer = MockWriter()
    queue = AsyncUsageWriteQueue(writer, batch_size=10, flush_interval_seconds=0.1)
    await queue.start()

    from datetime import datetime, timezone
    from src.core.domain.traffic_leg import TrafficLeg

    records = [
        UsageRecord(
            id=f"rec-{i}",
            timestamp=datetime.now(timezone.utc),
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
        for i in range(100)
    ]

    errors = []

    async def enqueue_batch(recs):
        batch_errors = []
        for r in recs:
            try:
                queue.enqueue_insert(r)
            except Exception as e:
                batch_errors.append(e)
        return batch_errors

    async def access_stats():
        batch_errors = []
        for _ in range(50):
            try:
                stats = queue.statistics
            except Exception as e:
                batch_errors.append(e)
        return batch_errors

    tasks = [enqueue_batch(records) for _ in range(5)] + [access_stats() for _ in range(5)]
    all_errors = await asyncio.gather(*tasks)
    for batch_errors in all_errors:
        errors.extend(batch_errors)

    await queue.stop()

    print(f"Total errors: {len(errors)}")
    if errors:
        for e in errors[:5]:
            print(f"  Error: {e}")
    print(f"Final stats: {queue.statistics}")

    return len(errors) == 0


if __name__ == "__main__":
    success = asyncio.run(test_concurrent_statistics_updates())
    if success:
        print("PASS: No race condition detected")
    else:
        print("FAIL: Race condition or errors detected")
        sys.exit(1)
