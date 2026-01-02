"""
Meta test to detect duplicate test file names.

This test ensures that there are no duplicate test file names across the test suite,
which can cause pytest collection issues and test interference.

Note to LLM agents: You are **NOT ALLOWED** to skip, disable, mute or alter this test
unless EXPLICITLY INSTRUCTED BY HUMAN OPERATOR.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest


def test_no_duplicate_test_file_names() -> None:
    """
    Test that there are no duplicate test file names in the test suite.

    This test scans all test_*.py files and checks if any filename appears
    multiple times. If duplicates are found, it fails and prints their locations.
    """
    project_root = Path(__file__).parent.parent
    tests_dir = project_root / "tests"

    if not tests_dir.exists():
        pytest.skip("Tests directory not found")

    # Map filename -> list of full paths
    filename_to_paths: defaultdict[str, list[Path]] = defaultdict(list)

    # Scan all test_*.py files
    for test_file in tests_dir.rglob("test_*.py"):
        if test_file.is_file():
            filename = test_file.name
            filename_to_paths[filename].append(test_file)

    # Find duplicates
    duplicates: dict[str, list[Path]] = {
        filename: paths
        for filename, paths in filename_to_paths.items()
        if len(paths) > 1
    }

    if duplicates:
        # Build error message with all duplicates
        error_lines = [
            "Duplicate test file names detected!",
            "",
            "The following test file names appear multiple times:",
            "",
        ]

        for filename, paths in sorted(duplicates.items()):
            error_lines.append(f"  '{filename}' found in {len(paths)} locations:")
            for path in sorted(paths):
                # Use relative path from project root for readability
                rel_path = path.relative_to(project_root)
                error_lines.append(f"    - {rel_path}")

        error_message = "\n".join(error_lines)
        pytest.fail(error_message)

    # If we get here, no duplicates were found
    assert True, "No duplicate test file names found"
