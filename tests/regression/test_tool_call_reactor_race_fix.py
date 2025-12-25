"""Regression test for tool_call_reactor_service race conditions."""

import sys
import threading
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.services.tool_call_reactor_service import ToolCallReactorService


def test_concurrent_tool_argument_repair_stats():
    """Test that _tool_argument_repair_stats is thread-safe."""
    service = ToolCallReactorService()

    threads = []
    num_threads = 10
    increments_per_thread = 100

    def increment_success():
        for _ in range(increments_per_thread):
            service.record_tool_argument_repair_outcome("success")

    def increment_failed():
        for _ in range(increments_per_thread):
            service.record_tool_argument_repair_outcome("failed")

    def increment_recovered():
        for _ in range(increments_per_thread):
            service.record_tool_argument_repair_outcome("recovered")

    # Create threads
    for _ in range(num_threads):
        threads.append(threading.Thread(target=increment_success))
        threads.append(threading.Thread(target=increment_failed))
        threads.append(threading.Thread(target=increment_recovered))

    # Start all threads
    for t in threads:
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join()

    stats = service.get_tool_argument_repair_stats()

    expected_success = num_threads * increments_per_thread
    expected_failed = num_threads * increments_per_thread
    expected_recovered = num_threads * increments_per_thread

    assert stats["success"] == expected_success, (
        f"Expected {expected_success} success counts, got {stats['success']}"
    )
    assert stats["failed"] == expected_failed, (
        f"Expected {expected_failed} failed counts, got {stats['failed']}"
    )
    assert stats["recovered"] == expected_recovered, (
        f"Expected {expected_recovered} recovered counts, got {stats['recovered']}"
    )


def test_concurrent_telemetry_counters():
    """Test that telemetry counters are thread-safe."""
    service = ToolCallReactorService()

    threads = []
    num_threads = 20
    increments_per_thread = 50

    def increment_filtered():
        for _ in range(increments_per_thread):
            service.increment_tool_definitions_filtered()

    def increment_blocked():
        for _ in range(increments_per_thread):
            service.increment_tool_calls_blocked()

    def increment_allowed():
        for _ in range(increments_per_thread):
            service.increment_tool_calls_allowed()

    # Create threads
    for _ in range(num_threads):
        threads.append(threading.Thread(target=increment_filtered))
        threads.append(threading.Thread(target=increment_blocked))
        threads.append(threading.Thread(target=increment_allowed))

    # Start all threads
    for t in threads:
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join()

    telemetry = service.get_telemetry_stats()

    expected_filtered = num_threads * increments_per_thread
    expected_blocked = num_threads * increments_per_thread
    expected_allowed = num_threads * increments_per_thread

    assert telemetry["tool_definitions_filtered"] == expected_filtered, (
        f"Expected {expected_filtered} filtered, got {telemetry['tool_definitions_filtered']}"
    )
    assert telemetry["tool_calls_blocked"] == expected_blocked, (
        f"Expected {expected_blocked} blocked, got {telemetry['tool_calls_blocked']}"
    )
    assert telemetry["tool_calls_allowed"] == expected_allowed, (
        f"Expected {expected_allowed} allowed, got {telemetry['tool_calls_allowed']}"
    )
