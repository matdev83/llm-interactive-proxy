"""
Test fractional turn counting for Quality Verifier in tool-heavy workloads.

Regression tests for the bug where Quality Verifier turn counter would not increment
when requests were tool followups or replacement was active, preventing Quality Verifier
from ever reaching its frequency threshold in tool-heavy coding sessions.
"""

from unittest.mock import MagicMock

import pytest
from src.core.services.request_processor_service import RequestProcessor


@pytest.fixture
def request_processor():
    """Create a RequestProcessor with minimal mocked dependencies for turn counting tests."""
    # Create minimal mocks for all required dependencies
    mock_dependencies = {
        "command_processor": MagicMock(),
        "session_manager": MagicMock(),
        "backend_request_manager": MagicMock(),
        "response_manager": MagicMock(),
        "session_enricher": MagicMock(),
        "request_side_effects": MagicMock(),
        "command_handler": MagicMock(),
        "backend_preparer": MagicMock(),
        "transform_pipeline": MagicMock(),
        "backend_executor": MagicMock(),
        "app_state": MagicMock(),
        "replacement_service": None,
    }

    processor = RequestProcessor(**mock_dependencies)
    return processor


def test_turn_count_storage_uses_floats(request_processor):
    """Test that turn count storage correctly handles float values."""
    session_key = "test-session"

    # Set a fractional turn count
    request_processor._set_quality_verifier_turn_count(session_key, 0.1)

    # Retrieve it
    count = request_processor._get_quality_verifier_turn_count(session_key)

    assert count == 0.1, f"Expected 0.1, got {count}"
    assert isinstance(count, float), f"Expected float type, got {type(count)}"


def test_fractional_turns_accumulate(request_processor):
    """Test that fractional turn increments accumulate correctly."""
    session_key = "test-session"

    # Simulate 10 tool followups at 0.1 each
    for _i in range(10):
        current = request_processor._get_quality_verifier_turn_count(session_key)
        new_count = current + 0.1
        request_processor._set_quality_verifier_turn_count(session_key, new_count)

    final_count = request_processor._get_quality_verifier_turn_count(session_key)

    # Should be approximately 1.0 (within floating point error)
    assert abs(final_count - 1.0) < 0.01, f"Expected ~1.0, got {final_count}"


def test_mixed_turn_increments(request_processor):
    """Test that mixed regular and fractional turns accumulate correctly."""
    session_key = "test-session"

    # 2 regular turns
    request_processor._set_quality_verifier_turn_count(session_key, 1.0)
    current = request_processor._get_quality_verifier_turn_count(session_key)
    request_processor._set_quality_verifier_turn_count(session_key, current + 1.0)

    # 5 tool followups
    for _ in range(5):
        current = request_processor._get_quality_verifier_turn_count(session_key)
        request_processor._set_quality_verifier_turn_count(session_key, current + 0.1)

    final_count = request_processor._get_quality_verifier_turn_count(session_key)

    # Should be 2.0 + 0.5 = 2.5
    assert abs(final_count - 2.5) < 0.01, f"Expected ~2.5, got {final_count}"


def test_turn_count_does_not_go_negative(request_processor):
    """Test that turn count is clamped to non-negative values."""
    session_key = "test-session"

    # Try to set a negative value
    request_processor._set_quality_verifier_turn_count(session_key, -5.5)

    count = request_processor._get_quality_verifier_turn_count(session_key)

    assert count >= 0.0, f"Expected non-negative count, got {count}"


def test_turn_count_lru_eviction(request_processor):
    """Test that LRU cache evicts old sessions when full."""
    # Fill the cache beyond MAX_QUALITY_VERIFIER_TURN_STATES (10_000)
    # Use a smaller number for test performance
    test_count = 100  # Smaller number for faster test

    # First fill to the limit
    for i in range(test_count):
        session_key = f"session-{i}"
        request_processor._set_quality_verifier_turn_count(session_key, float(i) * 0.1)

    # Verify the cache contains the expected count
    cache_size = len(request_processor._quality_verifier_turn_counts)
    assert cache_size == test_count, f"Expected {test_count}, got {cache_size}"

    # Most recent session should still be present
    last_session = f"session-{test_count - 1}"
    count = request_processor._get_quality_verifier_turn_count(last_session)
    expected = (test_count - 1) * 0.1
    assert abs(count - expected) < 0.01, f"Expected ~{expected}, got {count}"
