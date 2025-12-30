"""Pytest configuration for Codex backend tests.

All tests in this directory are automatically marked with @pytest.mark.codex
and are now included in default test runs.

To run only codex tests:
    ./.venv/Scripts/python.exe -m pytest -m codex
"""

import pytest


def pytest_collection_modifyitems(config, items):
    """Auto-apply codex marker to all tests in this directory."""
    # Cache path markers to avoid repeated string operations
    codex_path_unix = "tests/codex"
    codex_path_win = "tests\\codex"
    for item in items:
        # Cache fspath string conversion
        fspath_str = str(item.fspath)
        if codex_path_unix in fspath_str or codex_path_win in fspath_str:
            item.add_marker(pytest.mark.codex)
