"""Tests for real-time-dependent test marker.

This module tests the pytest marker for identifying tests that legitimately
require real system wall-clock time.
"""

import pytest


def test_real_time_marker_is_registered(pytestconfig: pytest.Config) -> None:
    """Test that the real_time marker is registered with pytest."""
    # Get all registered markers
    markers = pytestconfig.getini("markers")

    # Check that real_time marker is registered
    real_time_marker = [m for m in markers if m.startswith("real_time:")]
    assert len(real_time_marker) > 0, "real_time marker should be registered"


def test_real_time_marker_requires_reason() -> None:
    """Test that the real_time marker requires a non-empty reason parameter."""
    from tests.unit.fixtures.markers import real_time

    # Should accept non-empty reason
    marker = real_time(reason="This test measures actual elapsed time")
    assert marker is not None

    # Should raise error for empty reason
    with pytest.raises(ValueError, match="non-empty reason"):
        real_time(reason="")

    # Should raise error for whitespace-only reason
    with pytest.raises(ValueError, match="non-empty reason"):
        real_time(reason="   ")


def test_real_time_marker_can_be_applied_to_test() -> None:
    """Test that the real_time marker can be applied to test functions."""
    from tests.unit.fixtures.markers import real_time

    @real_time(reason="Test requires real system time")
    def test_example() -> None:
        pass

    # Verify marker is applied
    assert hasattr(test_example, "pytestmark")
    markers = getattr(test_example, "pytestmark", [])
    assert any(
        hasattr(m, "name") and m.name == "real_time" for m in markers
    ), "Test should have real_time marker"


def test_real_time_marker_appears_in_pytest_markers_list(
    pytestconfig: pytest.Config,
) -> None:
    """Test that real_time marker appears in pytest marker configuration."""
    # Get all registered markers
    markers = pytestconfig.getini("markers")

    # Check that real_time marker is registered (should appear in the list)
    real_time_found = any("real_time" in m for m in markers)
    assert (
        real_time_found
    ), "real_time marker should be registered in pytest configuration"
