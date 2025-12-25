"""Repro script for race condition in UsageRecordingService._turn_counters."""
import asyncio
import sys
import tempfile
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def record_request_concurrently():
    """Simulate concurrent record_request calls to expose race condition."""
    from src.core.domain.traffic_leg import TrafficLeg
    from src.core.services.in_memory_usage_store import InMemoryUsageStore
    from src.core.services.usage_recording_service import UsageRecordingService

    with tempfile.TemporaryDirectory() as tmpdir:
        store = InMemoryUsageStore(
            persistence_path=Path(tmpdir) / "usage.db",
            flush_interval_seconds=60.0,
            max_records_in_memory=10000,
        )

        service = UsageRecordingService(store)
        session_id = "test-session-123"

        # Record 100 requests concurrently
        tasks = [
            service.record_request(
                session_id=session_id,
                backend_type="openai",
                model="gpt-4",
                frontend_type="openai",
                leg=TrafficLeg.CLIENT_TO_PROXY,
                prompt_tokens=100,
            )
            for _ in range(100)
        ]

        await asyncio.gather(*tasks)

        # Check for gaps in turn numbers
        records = list(store._records.values())
        records.sort(key=lambda r: r.turn_number)

        turn_numbers = [r.turn_number for r in records if r.session_id == session_id]
        expected = list(range(1, 101))
        missing = set(expected) - set(turn_numbers)
        duplicates = [t for t in turn_numbers if turn_numbers.count(t) > 1]

        print(f"Total records: {len(records)}")
        print("Expected turn numbers: 1-100")
        print(f"Actual turn numbers: {sorted(set(turn_numbers))}")
        print(f"Missing: {sorted(missing) if missing else 'None'}")
        print(f"Duplicates: {set(duplicates) if duplicates else 'None'}")

        if missing or duplicates:
            print("RACE CONDITION DETECTED!")
            return False
        else:
            print("No race condition detected")
            return True
    session_id = "test-session-123"

    # Record 100 requests concurrently
    tasks = [
        service.record_request(
            session_id=session_id,
            backend_type="openai",
            model="gpt-4",
            frontend_type="openai",
            leg=0,  # TrafficLeg.CLIENT_TO_PROXY
            prompt_tokens=100,
        )
        for _ in range(100)
    ]

    await asyncio.gather(*tasks)

    # Check for gaps in turn numbers
    records = list(store._records.values())
    records.sort(key=lambda r: r.turn_number)

    turn_numbers = [r.turn_number for r in records if r.session_id == session_id]
    expected = list(range(1, 101))
    missing = set(expected) - set(turn_numbers)
    duplicates = [t for t in turn_numbers if turn_numbers.count(t) > 1]

    print(f"Total records: {len(records)}")
    print("Expected turn numbers: 1-100")
    print(f"Actual turn numbers: {sorted(set(turn_numbers))}")
    print(f"Missing: {sorted(missing) if missing else 'None'}")
    print(f"Duplicates: {set(duplicates) if duplicates else 'None'}")

    if missing or duplicates:
        print("RACE CONDITION DETECTED!")
        return False
    else:
        print("No race condition detected")
        return True


if __name__ == "__main__":
    for i in range(10):
        print(f"\n--- Run {i+1} ---")
        success = asyncio.run(record_request_concurrently())
        if not success:
            print("Failed on first error - exiting")
            break
