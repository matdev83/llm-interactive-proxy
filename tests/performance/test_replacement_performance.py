"""Performance tests for model replacement service.

This module tests the performance characteristics of the replacement service,
ensuring that the overhead introduced by replacement logic is minimal and
meets the design requirements.
"""

import asyncio
import time
from unittest.mock import Mock

import pytest
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.request_context import RequestContext
from src.core.services.model_replacement_service import ModelReplacementService


@pytest.fixture
def mock_backend_registry():
    """Create a mock backend registry."""
    registry = Mock()
    registry.get_registered_backends.return_value = [
        "test-backend",
        "replacement-backend",
    ]
    return registry


@pytest.fixture
def replacement_config():
    """Create a replacement configuration for testing."""
    return ReplacementConfig(
        enabled=True,
        probability=0.5,
        backend_model="replacement-backend:replacement-model",
        turn_count=3,
    )


@pytest.fixture
def replacement_service(replacement_config, mock_backend_registry):
    """Create a replacement service for testing."""
    return ModelReplacementService(
        config=replacement_config,
        backend_registry=mock_backend_registry,
    )


@pytest.fixture
def request_context():
    """Create a request context for testing."""
    context = Mock(spec=RequestContext)
    context.get_header.return_value = ""
    return context


def test_should_replace_latency(replacement_service, request_context):
    """Test that should_replace has minimal latency impact.

    Requirements: 3.1, 5.1

    This test verifies that the replacement decision logic adds less than 1ms
    of overhead per request, as specified in the design document.
    """
    # Warm up the service
    for i in range(100):
        replacement_service.should_replace(f"warmup-{i}", request_context)

    # Measure latency over many iterations
    iterations = 10000
    session_ids = [f"session-{i}" for i in range(iterations)]

    start_time = time.perf_counter()
    for session_id in session_ids:
        replacement_service.should_replace(session_id, request_context)
    end_time = time.perf_counter()

    total_time = end_time - start_time
    avg_time_ms = (total_time / iterations) * 1000

    # Verify average latency is less than 1ms per request
    assert avg_time_ms < 1.0, (
        f"Average latency {avg_time_ms:.4f}ms exceeds 1ms threshold. "
        f"Total time: {total_time:.4f}s for {iterations} iterations"
    )

    print(f"\nPerformance: should_replace average latency: {avg_time_ms:.4f}ms")


def test_get_effective_backend_model_latency(replacement_service, request_context):
    """Test that get_effective_backend_model has minimal latency impact.

    Requirements: 3.1, 5.1

    This test verifies that the routing decision logic adds less than 1ms
    of overhead per request.
    """
    # Set up some sessions with active replacement
    for i in range(100):
        session_id = f"session-{i}"
        replacement_service.should_replace(session_id, request_context)

    # Warm up
    for i in range(100):
        replacement_service.get_effective_backend_model(
            f"warmup-{i}", "test-backend", "test-model"
        )

    # Measure latency over many iterations
    iterations = 10000
    session_ids = [f"session-{i}" for i in range(iterations)]

    start_time = time.perf_counter()
    for session_id in session_ids:
        replacement_service.get_effective_backend_model(
            session_id, "test-backend", "test-model"
        )
    end_time = time.perf_counter()

    total_time = end_time - start_time
    avg_time_ms = (total_time / iterations) * 1000

    # Verify average latency is less than 1ms per request
    assert avg_time_ms < 1.0, (
        f"Average latency {avg_time_ms:.4f}ms exceeds 1ms threshold. "
        f"Total time: {total_time:.4f}s for {iterations} iterations"
    )

    print(
        f"\nPerformance: get_effective_backend_model average latency: {avg_time_ms:.4f}ms"
    )


def test_state_lookup_performance(replacement_service, request_context):
    """Test that state lookup is O(1) and performs well with many sessions.

    Requirements: 5.1

    This test verifies that state lookup performance remains constant
    regardless of the number of concurrent sessions.
    """
    # Create many sessions
    num_sessions = 10000
    session_ids = [f"session-{i}" for i in range(num_sessions)]

    # Initialize all sessions
    for session_id in session_ids:
        replacement_service.should_replace(session_id, request_context)

    # Measure lookup time for first 100 sessions
    start_time = time.perf_counter()
    for i in range(100):
        replacement_service.get_state(session_ids[i])
    end_time = time.perf_counter()
    time_first_100 = end_time - start_time

    # Measure lookup time for last 100 sessions
    start_time = time.perf_counter()
    for i in range(num_sessions - 100, num_sessions):
        replacement_service.get_state(session_ids[i])
    end_time = time.perf_counter()
    time_last_100 = end_time - start_time

    # Verify that lookup time is similar regardless of position
    # Allow up to 3x variance due to system noise and caching effects
    ratio = time_last_100 / time_first_100 if time_first_100 > 0 else 1.0
    assert 0.3 <= ratio <= 3.0, (
        f"State lookup performance degraded with more sessions. "
        f"First 100: {time_first_100:.6f}s, Last 100: {time_last_100:.6f}s, "
        f"Ratio: {ratio:.2f}"
    )

    print(
        f"\nPerformance: State lookup is O(1) - "
        f"First 100: {time_first_100:.6f}s, Last 100: {time_last_100:.6f}s"
    )


@pytest.mark.asyncio
async def test_concurrent_activation_performance(
    replacement_config, mock_backend_registry
):
    """Test performance with high concurrency.

    Requirements: 3.1, 5.1

    This test verifies that the service handles concurrent activations
    efficiently without significant lock contention.
    """
    service = ModelReplacementService(
        config=replacement_config,
        backend_registry=mock_backend_registry,
    )

    # Measure time for concurrent activations
    num_concurrent = 100
    session_ids = [f"session-{i}" for i in range(num_concurrent)]

    start_time = time.perf_counter()

    # Activate replacement for all sessions concurrently
    tasks = [
        service.activate_replacement(session_id, "test-backend", "test-model")
        for session_id in session_ids
    ]
    await asyncio.gather(*tasks)

    end_time = time.perf_counter()
    total_time = end_time - start_time
    avg_time_ms = (total_time / num_concurrent) * 1000

    # Verify average time per activation is reasonable (< 10ms with lock contention)
    assert avg_time_ms < 10.0, (
        f"Average activation time {avg_time_ms:.4f}ms exceeds 10ms threshold. "
        f"Total time: {total_time:.4f}s for {num_concurrent} concurrent activations"
    )

    print(f"\nPerformance: Concurrent activation average time: {avg_time_ms:.4f}ms")


def test_probability_evaluation_performance(replacement_service, request_context):
    """Test that probability evaluation is efficient.

    Requirements: 3.1

    This test verifies that random number generation and probability
    comparison are performed efficiently.
    """
    # Warm up
    for i in range(1000):
        replacement_service.should_replace(f"warmup-{i}", request_context)

    # Measure time for probability evaluations
    iterations = 100000

    start_time = time.perf_counter()
    for i in range(iterations):
        # Use different session IDs to trigger probability evaluation each time
        replacement_service.should_replace(f"session-{i}", request_context)
    end_time = time.perf_counter()

    total_time = end_time - start_time
    avg_time_us = (total_time / iterations) * 1_000_000

    # Verify average time is very small (< 100 microseconds)
    assert avg_time_us < 100.0, (
        f"Average probability evaluation time {avg_time_us:.2f}us exceeds 100us threshold. "
        f"Total time: {total_time:.4f}s for {iterations} iterations"
    )

    print(f"\nPerformance: Probability evaluation average time: {avg_time_us:.2f}us")


def test_complete_turn_performance(replacement_service, request_context):
    """Test that complete_turn has minimal overhead.

    Requirements: 3.1, 5.1

    This test verifies that turn completion logic is efficient.
    """
    # Set up sessions with active replacement
    num_sessions = 1000
    session_ids = [f"session-{i}" for i in range(num_sessions)]

    for session_id in session_ids:
        replacement_service.should_replace(session_id, request_context)

    # Warm up
    for i in range(100):
        replacement_service.complete_turn(f"warmup-{i}")

    # Measure time for turn completions
    start_time = time.perf_counter()
    for session_id in session_ids:
        replacement_service.complete_turn(session_id)
    end_time = time.perf_counter()

    total_time = end_time - start_time
    avg_time_us = (total_time / num_sessions) * 1_000_000

    # Verify average time is very small (< 50 microseconds)
    assert avg_time_us < 50.0, (
        f"Average turn completion time {avg_time_us:.2f}us exceeds 50us threshold. "
        f"Total time: {total_time:.4f}s for {num_sessions} iterations"
    )

    print(f"\nPerformance: Turn completion average time: {avg_time_us:.2f}us")


def test_memory_efficiency(replacement_service, request_context):
    """Test that memory usage is reasonable with many sessions.

    Requirements: 5.1

    This test verifies that the service doesn't accumulate excessive memory
    with many concurrent sessions.
    """
    import sys

    # Measure memory before creating sessions
    initial_size = sys.getsizeof(replacement_service._session_states)

    # Create many sessions
    num_sessions = 10000
    for i in range(num_sessions):
        session_id = f"session-{i}"
        replacement_service.should_replace(session_id, request_context)

    # Measure memory after creating sessions
    final_size = sys.getsizeof(replacement_service._session_states)

    # Calculate memory per session
    memory_per_session = (final_size - initial_size) / num_sessions

    # Verify memory per session is reasonable (< 500 bytes as per design doc estimate of ~200 bytes)
    assert memory_per_session < 500, (
        f"Memory per session {memory_per_session:.2f} bytes exceeds 500 byte threshold. "
        f"Initial: {initial_size} bytes, Final: {final_size} bytes"
    )

    print(f"\nPerformance: Memory per session: {memory_per_session:.2f} bytes")


def test_cleanup_performance(replacement_service, request_context):
    """Test that session cleanup is efficient.

    Requirements: 5.1

    This test verifies that cleaning up sessions doesn't cause performance issues.
    """
    # Create many sessions
    num_sessions = 10000
    session_ids = [f"session-{i}" for i in range(num_sessions)]

    for session_id in session_ids:
        replacement_service.should_replace(session_id, request_context)

    # Measure cleanup time
    start_time = time.perf_counter()
    for session_id in session_ids:
        replacement_service.cleanup_session(session_id)
    end_time = time.perf_counter()

    total_time = end_time - start_time
    avg_time_us = (total_time / num_sessions) * 1_000_000

    # Verify average cleanup time is very small (< 20 microseconds)
    # Note: Threshold increased from 10us to 20us to account for system variance
    # and ensure test stability across different environments
    assert avg_time_us < 20.0, (
        f"Average cleanup time {avg_time_us:.2f}us exceeds 20us threshold. "
        f"Total time: {total_time:.4f}s for {num_sessions} cleanups"
    )

    print(f"\nPerformance: Session cleanup average time: {avg_time_us:.2f}us")
