"""Tests for time policy allow-list mechanism.

This module tests the allow-list mechanism for approved real-time exceptions.
"""

import json
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def allowlist_file(tmp_path: Path) -> Path:
    """Create a temporary allow-list file for testing."""
    return tmp_path / "time_policy_allowlist.json"


@pytest.fixture
def sample_allowlist_data() -> dict[str, Any]:
    """Sample allow-list data for testing."""
    return {
        "version": 1,
        "entries": [
            {
                "target_type": "nodeid",
                "target": "tests/unit/test_example.py::test_specific",
                "reason": "This test measures actual network latency",
            },
            {
                "target_type": "glob",
                "target": "tests/live/**/*.py",
                "reason": "Live tests require real time for API interactions",
            },
            {
                "target_type": "glob",
                "target": "tests/performance/**/*.py",
                "reason": "Performance tests measure actual execution time",
            },
        ],
    }


def test_load_allowlist_valid_json(
    allowlist_file: Path, sample_allowlist_data: dict[str, Any]
) -> None:
    """Test loading a valid allow-list JSON file."""
    from tests.utils.time_policy import load_allowlist

    # Write sample data to file
    allowlist_file.write_text(
        json.dumps(sample_allowlist_data, indent=2), encoding="utf-8"
    )

    # Load allow-list
    result = load_allowlist(allowlist_file)

    assert result["version"] == 1
    assert len(result["entries"]) == 3
    assert result["entries"][0]["target_type"] == "nodeid"
    assert result["entries"][0]["target"] == "tests/unit/test_example.py::test_specific"


def test_load_allowlist_invalid_json(allowlist_file: Path) -> None:
    """Test loading an invalid JSON file."""
    from tests.utils.time_policy import load_allowlist

    # Write invalid JSON
    allowlist_file.write_text("{ invalid json }", encoding="utf-8")

    # Should raise an error or return None
    with pytest.raises((json.JSONDecodeError, ValueError)):
        load_allowlist(allowlist_file)


def test_load_allowlist_missing_file() -> None:
    """Test loading a non-existent allow-list file."""
    from tests.utils.time_policy import load_allowlist

    missing_file = Path("/nonexistent/path/allowlist.json")
    result = load_allowlist(missing_file)

    # Should return empty/default structure or raise FileNotFoundError
    # Based on design, let's return empty structure
    assert result is not None
    assert result.get("version") == 1
    assert result.get("entries") == []


def test_load_allowlist_invalid_version(allowlist_file: Path) -> None:
    """Test loading allow-list with invalid version."""
    from tests.utils.time_policy import load_allowlist

    invalid_data = {"version": 999, "entries": []}
    allowlist_file.write_text(json.dumps(invalid_data), encoding="utf-8")

    # Should handle version mismatch gracefully
    result = load_allowlist(allowlist_file)
    # May return empty or raise - let's check what makes sense
    assert result is not None


def test_load_allowlist_empty_reason_rejected(allowlist_file: Path) -> None:
    """Test that allow-list entries with empty reason are rejected."""
    from tests.utils.time_policy import load_allowlist

    # Entry with empty reason
    invalid_data = {
        "version": 1,
        "entries": [
            {
                "target_type": "nodeid",
                "target": "tests/unit/test_example.py::test_specific",
                "reason": "",
            }
        ],
    }
    allowlist_file.write_text(json.dumps(invalid_data), encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty"):
        load_allowlist(allowlist_file)

    # Entry with whitespace-only reason
    invalid_data["entries"][0]["reason"] = "   "
    allowlist_file.write_text(json.dumps(invalid_data), encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty"):
        load_allowlist(allowlist_file)


def test_is_exempted_nodeid_match(
    allowlist_file: Path, sample_allowlist_data: dict[str, Any]
) -> None:
    """Test that nodeid matching works correctly."""
    from tests.utils.time_policy import is_exempted, load_allowlist

    allowlist_file.write_text(
        json.dumps(sample_allowlist_data, indent=2), encoding="utf-8"
    )
    allowlist = load_allowlist(allowlist_file)

    # Exact nodeid match
    assert (
        is_exempted(
            "tests/unit/test_example.py::test_specific",
            allowlist,
        )
        is True
    )

    # Non-matching nodeid
    assert (
        is_exempted(
            "tests/unit/test_example.py::test_other",
            allowlist,
        )
        is False
    )


def test_is_exempted_glob_match(
    allowlist_file: Path, sample_allowlist_data: dict[str, Any]
) -> None:
    """Test that glob pattern matching works correctly."""
    from tests.utils.time_policy import is_exempted, load_allowlist

    allowlist_file.write_text(
        json.dumps(sample_allowlist_data, indent=2), encoding="utf-8"
    )
    allowlist = load_allowlist(allowlist_file)

    # File matching glob pattern
    assert is_exempted("tests/live/test_api.py", allowlist) is True
    assert is_exempted("tests/live/subdir/test_other.py", allowlist) is True

    # File not matching glob pattern
    assert is_exempted("tests/unit/test_example.py", allowlist) is False


def test_is_exempted_precedence_nodeid_over_glob(
    allowlist_file: Path, sample_allowlist_data: dict[str, Any]
) -> None:
    """Test that nodeid matches take precedence over glob matches."""
    from tests.utils.time_policy import is_exempted, load_allowlist

    # Add a nodeid that matches a file also covered by glob
    sample_allowlist_data["entries"].append(
        {
            "target_type": "nodeid",
            "target": "tests/live/test_api.py::test_specific",
            "reason": "Specific test exception",
        }
    )

    allowlist_file.write_text(
        json.dumps(sample_allowlist_data, indent=2), encoding="utf-8"
    )
    allowlist = load_allowlist(allowlist_file)

    # Nodeid should match first
    assert is_exempted("tests/live/test_api.py::test_specific", allowlist) is True

    # Other tests in same file should match glob
    assert is_exempted("tests/live/test_api.py::test_other", allowlist) is True


def test_is_exempted_empty_allowlist(allowlist_file: Path) -> None:
    """Test that empty allow-list returns False for all queries."""
    from tests.utils.time_policy import is_exempted, load_allowlist

    empty_data = {"version": 1, "entries": []}
    allowlist_file.write_text(json.dumps(empty_data), encoding="utf-8")
    allowlist = load_allowlist(allowlist_file)

    assert is_exempted("tests/unit/test_example.py::test_specific", allowlist) is False
    assert is_exempted("tests/live/test_api.py", allowlist) is False


def test_is_exempted_with_marker() -> None:
    """Test that marker-based exemption is checked."""
    from tests.utils.time_policy import is_exempted

    # When a test has real_time marker, it should be exempted
    # This will be checked by the linter, but we can test the logic here
    empty_allowlist = {"version": 1, "entries": []}

    # For now, marker checking will be in the linter
    # This test verifies the allow-list doesn't interfere
    assert (
        is_exempted("tests/unit/test_example.py::test_specific", empty_allowlist)
        is False
    )
