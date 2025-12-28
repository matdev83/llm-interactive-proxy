"""Test concurrency safety of UsageRecordingService."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest
from src.core.domain.traffic_leg import TrafficLeg
from src.core.services.in_memory_usage_store import InMemoryUsageStore
from src.core.services.usage_recording_service import UsageRecordingService


@pytest.mark.asyncio
async def test_concurrent_record_request_turn_numbers() -> None:
    """Test that concurrent record_request calls produce unique turn numbers.

    This test verifies that the fix for the check-then-act race on
    _turn_counters prevents duplicate turn numbers from being assigned to
    concurrent requests for the same session.

    Without the lock, two coroutines could:
    1. Both see session_id not in _turn_counters
    2. Both initialize to 0
    3. Both increment to 1
    4. Both assign turn_number = 1
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        persistence_path = Path(tmp_dir) / "test_store.json"
        store = InMemoryUsageStore(persistence_path=persistence_path)
        service = UsageRecordingService(store)

        session_id = "test-session-concurrent"
        num_requests = 50

        # Launch 50 concurrent requests for the same session
        tasks = [
            service.record_request(
                session_id=session_id,
                backend_type="openai",
                model="gpt-4",
                frontend_type="openai",
                leg=TrafficLeg.CLIENT_TO_PROXY,
                prompt_tokens=100,
            )
            for _ in range(num_requests)
        ]

        # Wait for all requests to complete
        record_ids = await asyncio.gather(*tasks)

        # All records should have been created
        assert len(record_ids) == num_requests, "All requests should produce a record ID"

        # Retrieve all records
        records = store.get_records()
        session_records = [r for r in records if r.session_id == session_id]

        # Verify all records were stored
        assert len(session_records) == num_requests, f"Expected {num_requests} records, got {len(session_records)}"

        # Extract turn numbers
        turn_numbers = {r.turn_number for r in session_records}

        # All turn numbers should be unique and in range [1, num_requests]
        assert len(turn_numbers) == num_requests, (
            f"Turn numbers should be unique, got {len(turn_numbers)} unique values "
            f"out of {num_requests}: {sorted(turn_numbers)}"
        )
        assert min(turn_numbers) == 1, "Turn numbers should start at 1"
        assert max(turn_numbers) == num_requests, f"Turn numbers should go up to {num_requests}"


@pytest.mark.asyncio
async def test_concurrent_different_sessions() -> None:
    """Test that concurrent requests for different sessions work correctly.

    This ensures the lock doesn't cause unnecessary contention
    when requests are for different sessions (they still need the lock
    to prevent the check-then-act race, but we verify they don't interfere).
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        persistence_path = Path(tmp_dir) / "test_store.json"
        store = InMemoryUsageStore(persistence_path=persistence_path)
        service = UsageRecordingService(store)

        num_sessions = 10
        requests_per_session = 10

        # Create requests for multiple sessions concurrently
        tasks = []
        for session_idx in range(num_sessions):
            session_id = f"test-session-{session_idx}"
            for _ in range(requests_per_session):
                tasks.append(
                    service.record_request(
                        session_id=session_id,
                        backend_type="openai",
                        model="gpt-4",
                        frontend_type="openai",
                        leg=TrafficLeg.CLIENT_TO_PROXY,
                        prompt_tokens=100,
                    )
                )

        # Wait for all requests to complete
        await asyncio.gather(*tasks)

        # Verify records were created for all sessions
        records = store.get_records()
        assert len(records) == num_sessions * requests_per_session

        # Each session should have unique turn numbers
        for session_idx in range(num_sessions):
            session_id = f"test-session-{session_idx}"
            session_records = [r for r in records if r.session_id == session_id]
            assert len(session_records) == requests_per_session

            turn_numbers = [r.turn_number for r in session_records]
            assert len(set(turn_numbers)) == requests_per_session, (
                f"Session {session_id} should have unique turn numbers"
            )
            assert sorted(turn_numbers) == list(range(1, requests_per_session + 1)), (
                f"Session {session_id} should have sequential turn numbers"
            )
