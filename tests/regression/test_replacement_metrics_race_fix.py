"""Regression test for replacement_metrics race conditions."""

import sys
import threading
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.services.replacement_metrics import ReplacementMetrics


def test_concurrent_record_activation():
    """Test that record_activation is thread-safe."""
    metrics = ReplacementMetrics()

    threads = []
    num_threads = 20
    sessions_per_thread = 25

    def record_activations():
        for i in range(sessions_per_thread):
            session_id = f"session_{threading.get_ident()}_{i}"
            metrics.record_activation(session_id, turn_count=1)

    # Create and start threads
    for _ in range(num_threads):
        t = threading.Thread(target=record_activations)
        threads.append(t)
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join()

    # Verify all activations were recorded
    expected_activations = num_threads * sessions_per_thread
    assert metrics.total_activations == expected_activations, (
        f"Expected {expected_activations} total activations, got {metrics.total_activations}"
    )
    assert len(metrics.activation_timestamps) == expected_activations, (
        f"Expected {expected_activations} timestamps, got {len(metrics.activation_timestamps)}"
    )


def test_concurrent_record_opt_out():
    """Test that record_opt_out is thread-safe."""
    metrics = ReplacementMetrics()

    threads = []
    num_threads = 15
    sessions_per_thread = 20

    def record_opt_outs():
        for i in range(sessions_per_thread):
            session_id = f"session_{threading.get_ident()}_{i}"
            opt_out_type = "header" if i % 2 == 0 else "session"
            metrics.record_opt_out(session_id, opt_out_type)

    # Create and start threads
    for _ in range(num_threads):
        t = threading.Thread(target=record_opt_outs)
        threads.append(t)
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join()

    # Verify all opt-outs were recorded
    expected_opt_outs = num_threads * sessions_per_thread
    assert metrics.total_opt_outs == expected_opt_outs, (
        f"Expected {expected_opt_outs} total opt-outs, got {metrics.total_opt_outs}"
    )
    assert len(metrics.opt_out_timestamps) == expected_opt_outs, (
        f"Expected {expected_opt_outs} timestamps, got {len(metrics.opt_out_timestamps)}"
    )
    expected_header = sum(1 for i in range(sessions_per_thread) if i % 2 == 0) * num_threads
    expected_session = sum(1 for i in range(sessions_per_thread) if i % 2 == 1) * num_threads
    assert metrics.header_opt_outs == expected_header, (
        f"Expected {expected_header} header opt-outs, got {metrics.header_opt_outs}"
    )
    assert metrics.session_opt_outs == expected_session, (
        f"Expected {expected_session} session opt-outs, got {metrics.session_opt_outs}"
    )


def test_concurrent_mixed_operations():
    """Test that mixed concurrent operations are thread-safe."""
    metrics = ReplacementMetrics()

    threads = []
    num_threads = 10
    operations_per_thread = 30

    def mixed_operations():
        for i in range(operations_per_thread):
            session_id = f"session_{threading.get_ident()}_{i}"
            # Mix of different operations
            if i % 3 == 0:
                metrics.record_activation(session_id, turn_count=i)
            elif i % 3 == 1:
                metrics.record_opt_out(session_id, "header")
            else:
                metrics.record_turn_completion(session_id)

    # Create and start threads
    for _ in range(num_threads):
        t = threading.Thread(target=mixed_operations)
        threads.append(t)
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join()

    expected_activations = (operations_per_thread // 3) * num_threads
    expected_opt_outs = (operations_per_thread // 3) * num_threads
    expected_turn_completions = (
        operations_per_thread - (operations_per_thread // 3) * 2
    ) * num_threads

    assert metrics.total_activations == expected_activations, (
        f"Expected {expected_activations} activations, got {metrics.total_activations}"
    )
    assert metrics.total_opt_outs == expected_opt_outs, (
        f"Expected {expected_opt_outs} opt-outs, got {metrics.total_opt_outs}"
    )
    assert metrics.total_turns_completed == expected_turn_completions, (
        f"Expected {expected_turn_completions} turn completions, "
        f"got {metrics.total_turns_completed}"
    )


def test_concurrent_get_rates():
    """Test that get_activation_rate and get_opt_out_rate are thread-safe."""
    metrics = ReplacementMetrics()

    threads = []
    num_threads = 10
    records_per_thread = 20

    def record_and_get_rates():
        for i in range(records_per_thread):
            session_id = f"session_{threading.get_ident()}_{i}"
            metrics.record_activation(session_id, turn_count=1)
            # Concurrent read
            _ = metrics.get_activation_rate()

            metrics.record_opt_out(session_id, "header")
            # Concurrent read
            _ = metrics.get_opt_out_rate()

    # Create and start threads
    for _ in range(num_threads):
        t = threading.Thread(target=record_and_get_rates)
        threads.append(t)
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join()

    expected_activations = num_threads * records_per_thread
    expected_opt_outs = num_threads * records_per_thread

    assert metrics.total_activations == expected_activations, (
        f"Expected {expected_activations} activations, got {metrics.total_activations}"
    )
    assert metrics.total_opt_outs == expected_opt_outs, (
        f"Expected {expected_opt_outs} opt-outs, got {metrics.total_opt_outs}"
    )
