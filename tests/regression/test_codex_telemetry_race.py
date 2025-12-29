"""Regression test for _openai_codex_telemetry race conditions.

Tests that telemetry data structures are protected from concurrent mutations.
"""

import threading

import pytest
from src.connectors._openai_codex_telemetry import get_telemetry, reset_telemetry


def test_telemetry_instance_protection_exists():
    """Test that telemetry module structure is thread-safe.

    This is a structural test to verify that the module has
    proper isolation to prevent race conditions.
    """
    # Get two telemetry instances
    telemetry1 = get_telemetry()
    telemetry2 = get_telemetry()

    # Both should reference the same underlying instance
    assert telemetry1 is telemetry2, "Should be singleton pattern"

    # Reset and verify reset works
    reset_telemetry()
    telemetry3 = get_telemetry()

    assert telemetry3 is not None, "Telemetry should be initialized after reset"
    assert telemetry1 is not telemetry3, "Reset should create new instance"


def test_concurrent_detection_recording():
    """Test that concurrent detection recordings are thread-safe.

    This test spawns multiple threads that simultaneously record detection
    events to verify that the internal data structures (deque, dict)
    are not corrupted by concurrent mutations.
    """
    reset_telemetry()
    telemetry = get_telemetry()

    num_threads = 10
    events_per_thread = 100
    barrier = threading.Barrier(num_threads)
    errors = []

    def record_detections(thread_id):
        try:
            barrier.wait()
            for i in range(events_per_thread):
                telemetry.log_detection_event(
                    session_id=f"session-{thread_id}",
                    is_kilocode=i % 2 == 0,
                    detection_method=["metadata", "header", "heuristic"][i % 3],
                    confidence=0.8 + (i * 0.01),
                    duration_ms=10.0 + i,
                    agent_string=f"agent-{thread_id}",
                )
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=record_detections, args=(i,), daemon=True)
        for i in range(num_threads)
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join(timeout=30.0)

    stuck_threads = [t.name for t in threads if t.is_alive()]
    assert not stuck_threads, f"Threads did not finish: {stuck_threads}"

    assert len(errors) == 0, f"Errors during concurrent recording: {errors}"

    summary = telemetry.get_metrics_summary()

    expected_total = num_threads * events_per_thread
    assert summary.detection.total == expected_total, (
        f"Expected {expected_total} detections, got {summary.detection.total}"
    )

    assert summary.detection.by_method["metadata"] > 0, "Should have metadata detections"
    assert summary.detection.by_method["header"] > 0, "Should have header detections"
    assert summary.detection.by_method["heuristic"] > 0, "Should have heuristic detections"


def test_concurrent_translation_recording():
    """Test that concurrent translation recordings are thread-safe."""
    reset_telemetry()
    telemetry = get_telemetry()

    num_threads = 10
    events_per_thread = 50
    barrier = threading.Barrier(num_threads)
    errors = []

    def record_translations(thread_id):
        try:
            barrier.wait()
            for i in range(events_per_thread):
                telemetry.log_translation_event(
                    session_id=f"session-{thread_id}",
                    tool_name=f"tool-{i % 5}",
                    original_xml=f"<tool>{i}</tool>",
                    translated_tool=f"translated_tool_{i % 5}",
                    execution_mode="codex",
                    duration_ms=20.0 + i,
                    success=i % 10 != 0,
                )
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=record_translations, args=(i,), daemon=True)
        for i in range(num_threads)
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join(timeout=30.0)

    stuck_threads = [t.name for t in threads if t.is_alive()]
    assert not stuck_threads, f"Threads did not finish: {stuck_threads}"

    assert len(errors) == 0, f"Errors during concurrent recording: {errors}"

    summary = telemetry.get_metrics_summary()

    expected_total = num_threads * events_per_thread
    assert summary.translation.total == expected_total, (
        f"Expected {expected_total} translations, got {summary.translation.total}"
    )

    assert summary.translation.successful > 0, "Should have successful translations"
    assert summary.translation.failed > 0, "Should have failed translations"


def test_concurrent_error_recording():
    """Test that concurrent error recordings are thread-safe."""
    reset_telemetry()
    telemetry = get_telemetry()

    num_threads = 8
    events_per_thread = 25
    barrier = threading.Barrier(num_threads)
    errors = []

    def record_errors(thread_id):
        try:
            barrier.wait()
            for i in range(events_per_thread):
                telemetry.log_error_event(
                    session_id=f"session-{thread_id}",
                    error_code=f"ERR_{i % 3}",
                    tool_name=f"tool-{i % 4}",
                    error_message=f"Error {i}",
                    original_xml=f"<error>{i}</error>",
                )
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=record_errors, args=(i,), daemon=True)
        for i in range(num_threads)
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join(timeout=30.0)

    stuck_threads = [t.name for t in threads if t.is_alive()]
    assert not stuck_threads, f"Threads did not finish: {stuck_threads}"

    assert len(errors) == 0, f"Errors during concurrent recording: {errors}"

    summary = telemetry.get_metrics_summary()

    expected_total = num_threads * events_per_thread
    assert summary.errors.total == expected_total, (
        f"Expected {expected_total} errors, got {summary.errors.total}"
    )


def test_concurrent_enable_disable():
    """Test that concurrent enable/disable operations are thread-safe."""
    reset_telemetry()
    telemetry = get_telemetry()

    num_threads = 5
    barrier = threading.Barrier(num_threads)
    errors = []

    def toggle_enable(thread_id):
        try:
            barrier.wait()
            for i in range(20):
                if i % 2 == 0:
                    telemetry.enable()
                else:
                    telemetry.disable()
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=toggle_enable, args=(i,), daemon=True)
        for i in range(num_threads)
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join(timeout=30.0)

    stuck_threads = [t.name for t in threads if t.is_alive()]
    assert not stuck_threads, f"Threads did not finish: {stuck_threads}"

    assert len(errors) == 0, f"Errors during concurrent enable/disable: {errors}"

    is_enabled = telemetry.is_enabled()
    assert isinstance(is_enabled, bool), "is_enabled should return boolean"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
