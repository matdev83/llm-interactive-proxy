"""Pytest configuration for Codex backend tests.

All tests in this directory are automatically marked with @pytest.mark.codex
and excluded from default test runs to avoid CI/CD resource waste.

To run codex tests:
    ./.venv/Scripts/python.exe -m pytest -m codex

To run all tests INCLUDING codex:
    ./.venv/Scripts/python.exe -m pytest -m "not slow"
"""

import pytest


def pytest_collection_modifyitems(config, items):
    """Auto-apply codex marker to all tests in this directory."""
    for item in items:
        # Handle both Unix and Windows path separators
        fspath_str = str(item.fspath)
        if "tests/codex" in fspath_str or "tests\\codex" in fspath_str:
            item.add_marker(pytest.mark.codex)
