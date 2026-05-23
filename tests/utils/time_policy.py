"""Time control policy and allow-list for test time management.

This module provides:
- Allow-list loading and querying for approved real-time exceptions
- Policy documentation for choosing time-control techniques
- Constants and helpers for consistent time control selection

Policy Overview:
===============

The test suite enforces deterministic time behavior by requiring tests to use
test-controlled time sources instead of reading real system wall-clock time.
This policy ensures tests are deterministic, repeatable, and CI-stable.

Time Control Techniques (in order of preference):
-------------------------------------------------

1. ITimeSource + TimeOverride (PREFERRED)
   - Use for: Repository-owned deterministic code paths
   - Benefits: Single overrideable boundary, no patching required
   - When: Code under test can be refactored to depend on ITimeSource
   - Example: Services that generate timestamps for persisted data

2. FakeClockContext (from tests.utils.fake_clock)
   - Use for: Async scheduling and epoch seconds (time.time())
   - Benefits: ContextVar-based, safe for parallel execution
   - When: Testing async code with asyncio.sleep or time.time()
   - Limitations: Does NOT guard datetime.now() / date.today()
   - Example: Testing rate limiting with async delays

3. freezegun (transitional, for legacy code)
   - Use for: Datetime wall-clock APIs (datetime.now(), date.today())
   - Benefits: Works with code that directly calls datetime/date APIs
   - When: Code cannot be refactored to ITimeSource in current scope
   - Important: Avoid global freezing; use explicit per-test scoping
   - Example: Testing date-based business logic in legacy modules

4. pytest.mark.real_time (explicit exception)
   - Use for: Legitimate real-time-dependent tests
   - Requirements: Must include non-empty reason parameter
   - When: Test intent requires real system time
   - Examples:
     * Measuring actual network latency
     * Benchmarking real performance characteristics
     * Testing time-dependent external API behavior
   - Usage: @real_time(reason="This test measures actual API response time")

Exception Policy:
-----------------

Tests that legitimately require real system time must be explicitly marked:

1. Per-test exception: Use @real_time(reason="...") marker
2. Bulk exception: Add entry to tests/utils/time_policy_allowlist.json

Exception Precedence (when checking exemptions):
- Allow-list nodeid entries (most specific, highest priority)
- Per-test @real_time marker (applied to individual test functions)
- Allow-list glob patterns (least specific, lowest priority)

Note: Marker-based exemptions are checked by the time usage linter (Phase 3).
The allow-list mechanism (this module) handles nodeid and glob patterns only.

The time usage linter will enforce this policy and fail on unguarded
real-time reads unless explicitly exempted.
"""

import fnmatch
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AllowListEntry:
    """Represents a single allow-list entry."""

    target_type: str  # "nodeid" or "glob"
    target: str  # Pattern to match
    reason: str  # Justification for the exception


def load_allowlist(allowlist_path: Path | None = None) -> dict[str, Any]:
    """Load the time policy allow-list from JSON file.

    Args:
        allowlist_path: Path to allow-list file. If None, uses default location.

    Returns:
        Dictionary with "version" and "entries" keys. Returns default structure
        if file doesn't exist or is invalid.

    Raises:
        ValueError: If JSON is invalid or version is unsupported.
    """
    if allowlist_path is None:
        # Default location relative to this file
        allowlist_path = Path(__file__).parent / "time_policy_allowlist.json"

    if not allowlist_path.exists():
        # Return empty allow-list structure
        return {"version": 1, "entries": []}

    try:
        content = allowlist_path.read_text(encoding="utf-8")
        data = json.loads(content)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"Failed to load allow-list from {allowlist_path}: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(f"Allow-list must be a JSON object, got {type(data)}")

    version = data.get("version", 1)
    if version != 1:
        # For now, only version 1 is supported
        # Return empty structure for unknown versions
        return {"version": 1, "entries": []}

    entries = data.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError(f"Allow-list entries must be a list, got {type(entries)}")

    # Validate entry structure
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"Allow-list entry must be a dict, got {type(entry)}")
        if "target_type" not in entry:
            raise ValueError("Allow-list entry missing 'target_type'")
        if "target" not in entry:
            raise ValueError("Allow-list entry missing 'target'")
        if "reason" not in entry:
            raise ValueError("Allow-list entry missing 'reason'")
        if not entry["reason"] or not str(entry["reason"]).strip():
            raise ValueError(
                f"Allow-list entry 'reason' must be non-empty (entry: {entry.get('target', 'unknown')})"
            )
        if entry["target_type"] not in ("nodeid", "glob"):
            raise ValueError(f"Invalid target_type: {entry['target_type']}")

    return {"version": version, "entries": entries}


def is_exempted(test_identifier: str, allowlist: dict[str, Any] | None = None) -> bool:
    """Check if a test is exempted from time usage linter checks.

    Precedence order:
    1. Nodeid exact matches (most specific)
    2. Glob pattern matches (less specific)

    Args:
        test_identifier: Test identifier (nodeid like "tests/unit/test.py::test_func"
            or file path like "tests/unit/test.py")
        allowlist: Allow-list dictionary. If None, loads from default location.

    Returns:
        True if test is exempted, False otherwise.
    """
    if allowlist is None:
        allowlist = load_allowlist()

    entries = allowlist.get("entries", [])
    if not entries:
        return False

    # Extract file path from nodeid if present
    file_path = (
        test_identifier.split("::")[0] if "::" in test_identifier else test_identifier
    )

    # First pass: check for exact nodeid matches (highest precedence)
    for entry in entries:
        if entry["target_type"] == "nodeid" and entry["target"] == test_identifier:
            return True

    # Second pass: check for glob pattern matches
    for entry in entries:
        if entry["target_type"] == "glob":
            pattern = entry["target"]
            # Normalize paths to use forward slashes for consistency
            normalized_pattern = pattern.replace("\\", "/")
            normalized_path = file_path.replace("\\", "/")

            # Handle ** patterns: ** matches zero or more directories
            # Pattern like "tests/live/**/*.py" should match:
            # - tests/live/test.py (zero directories)
            # - tests/live/subdir/test.py (one directory)
            # - tests/live/subdir/nested/test.py (multiple directories)

            if "**" in normalized_pattern:
                # Split pattern at **
                parts = normalized_pattern.split("**", 1)
                prefix = parts[0].rstrip("/")
                suffix = parts[1].lstrip("/") if len(parts) > 1 else ""

                # Check if path starts with prefix
                if not normalized_path.startswith(prefix):
                    continue

                # Get the part after prefix
                after_prefix = normalized_path[len(prefix) :].lstrip("/")

                if not suffix:
                    # Pattern ends with **, match everything after prefix
                    return True

                # Check if suffix matches the end of the path
                # Suffix like "/*.py" or "*.py" should match files ending in .py
                if suffix.startswith("/"):
                    suffix = suffix[1:]

                # Try direct suffix match
                if after_prefix.endswith(suffix) or fnmatch.fnmatch(
                    after_prefix, suffix
                ):
                    return True

                # Try matching suffix anywhere in remaining path
                # For "*.py", check if any part matches
                if "*" in suffix:
                    if fnmatch.fnmatch(after_prefix, suffix):
                        return True
                    # Also try matching just the filename part
                    if "/" in after_prefix:
                        filename = after_prefix.split("/")[-1]
                        if fnmatch.fnmatch(filename, suffix):
                            return True
                elif suffix in after_prefix:
                    return True
            else:
                # Simple glob pattern, use fnmatch
                if fnmatch.fnmatch(normalized_path, normalized_pattern):
                    return True

    return False


# Policy constants and helpers

# Preferred time control technique (for documentation and IDE discovery)
PREFERRED_TIME_CONTROL = "ITimeSource + TimeOverride"

# Time control technique selection guide
TIME_CONTROL_GUIDE = {
    "ITimeSource + TimeOverride": {
        "use_for": "Repository-owned deterministic code paths",
        "when": "Code can be refactored to depend on ITimeSource",
        "benefits": [
            "Single overrideable boundary",
            "No patching required",
            "Eliminates patch brittleness",
        ],
        "example": "Services generating timestamps for persisted data",
    },
    "FakeClockContext": {
        "use_for": "Async scheduling and epoch seconds (time.time())",
        "when": "Testing async code with asyncio.sleep or time.time()",
        "benefits": [
            "ContextVar-based",
            "Safe for parallel execution",
        ],
        "limitations": ["Does NOT guard datetime.now() / date.today()"],
        "example": "Testing rate limiting with async delays",
        "import": "from tests.utils.fake_clock import FakeClockContext",
    },
    "unittest.mock.patch": {
        "use_for": "Sync tests with time.time() (transitional technique)",
        "when": "Testing synchronous code with time.time() that cannot use FakeClockContext",
        "benefits": ["Works with sync code", "Recognized by time usage linter"],
        "limitations": [
            "Does NOT guard datetime.now() / date.today()",
            "Less preferred than FakeClockContext for async code",
            "Transitional: prefer refactoring to ITimeSource when possible",
        ],
        "example": "Testing sync rate limiting logic",
        "import": "from unittest.mock import patch",
        "note": "Use FakeClockContext for async tests, patch for sync tests only",
    },
    "freezegun": {
        "use_for": "Datetime wall-clock APIs (datetime.now(), date.today())",
        "when": "Code cannot be refactored to ITimeSource in current scope",
        "benefits": ["Works with code that directly calls datetime/date APIs"],
        "important": "Avoid global freezing; use explicit per-test scoping",
        "example": "Testing date-based business logic in legacy modules",
        "import": "from freezegun import freeze_time",
    },
    "pytest.mark.real_time": {
        "use_for": "Legitimate real-time-dependent tests",
        "when": "Test intent requires real system time",
        "requirements": ["Must include non-empty reason parameter"],
        "examples": [
            "Measuring actual network latency",
            "Benchmarking real performance characteristics",
            "Testing time-dependent external API behavior",
        ],
        "import": "from tests.unit.fixtures.markers import real_time",
    },
}


def get_time_control_recommendation(use_case: str) -> str:
    """Get recommended time control technique for a use case.

    Args:
        use_case: Description of what you're testing (e.g., "async delays",
            "datetime timestamps", "legitimate performance measurement")

    Returns:
        Recommended technique name and brief guidance.

    Example:
        >>> get_time_control_recommendation("async delays")
        'FakeClockContext: Use for async scheduling and epoch seconds'
    """
    use_case_lower = use_case.lower()

    if (
        "async" in use_case_lower
        or "sleep" in use_case_lower
        or "time.time" in use_case_lower
    ):
        return "FakeClockContext: Use for async scheduling and epoch seconds"
    elif "datetime" in use_case_lower or "date.today" in use_case_lower:
        return (
            "freezegun: Use for datetime wall-clock APIs (or refactor to ITimeSource)"
        )
    elif (
        "performance" in use_case_lower
        or "latency" in use_case_lower
        or "benchmark" in use_case_lower
    ):
        return "pytest.mark.real_time: Use for legitimate real-time needs (with reason)"
    else:
        return "ITimeSource + TimeOverride: Preferred for deterministic code paths"
