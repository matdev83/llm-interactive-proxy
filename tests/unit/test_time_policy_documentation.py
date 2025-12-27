"""Tests for time policy documentation and helpers.

This module verifies that policy documentation is accessible and helpers work correctly.
"""

import inspect


def test_policy_module_can_be_imported() -> None:
    """Test that the time policy module can be imported."""
    from tests.utils import time_policy

    assert time_policy is not None
    assert hasattr(time_policy, "load_allowlist")
    assert hasattr(time_policy, "is_exempted")


def test_policy_constants_are_accessible() -> None:
    """Test that policy constants are accessible."""
    from tests.utils.time_policy import PREFERRED_TIME_CONTROL, TIME_CONTROL_GUIDE

    assert PREFERRED_TIME_CONTROL is not None
    assert isinstance(PREFERRED_TIME_CONTROL, str)
    assert TIME_CONTROL_GUIDE is not None
    assert isinstance(TIME_CONTROL_GUIDE, dict)


def test_policy_module_has_docstring() -> None:
    """Test that the policy module has comprehensive documentation."""
    from tests.utils import time_policy

    docstring = inspect.getdoc(time_policy)
    assert docstring is not None
    assert len(docstring) > 100, "Module should have comprehensive documentation"
    assert "Policy Overview" in docstring or "policy" in docstring.lower()


def test_time_control_guide_has_expected_keys() -> None:
    """Test that TIME_CONTROL_GUIDE has expected technique keys."""
    from tests.utils.time_policy import TIME_CONTROL_GUIDE

    expected_keys = [
        "ITimeSource + TimeOverride",
        "FakeClockContext",
        "freezegun",
        "pytest.mark.real_time",
    ]

    for key in expected_keys:
        assert key in TIME_CONTROL_GUIDE, f"TIME_CONTROL_GUIDE missing key: {key}"


def test_get_time_control_recommendation() -> None:
    """Test the time control recommendation helper function."""
    from tests.utils.time_policy import get_time_control_recommendation

    # Test async use case
    result = get_time_control_recommendation("async delays")
    assert "FakeClockContext" in result

    # Test datetime use case
    result = get_time_control_recommendation("datetime timestamps")
    assert "freezegun" in result or "ITimeSource" in result

    # Test performance use case
    result = get_time_control_recommendation("performance measurement")
    assert "real_time" in result

    # Test default case
    result = get_time_control_recommendation("general deterministic test")
    assert "ITimeSource" in result or "TimeOverride" in result
