"""
Meta test to protect against test suite regression.

This test ensures that the number of tests in the suite does not decrease
over time, which would indicate that tests have been removed.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


class TestSuiteProtection:
    """Meta test to ensure test suite doesn't shrink."""

    STATE_FILE_PATH = Path(__file__).parent.parent / "data" / "test_suite_state.json"

    @classmethod
    def get_stored_test_count(cls) -> int | None:
        """Get the stored test count from the state file."""
        try:
            if cls.STATE_FILE_PATH.exists():
                with open(cls.STATE_FILE_PATH) as f:
                    data = json.load(f)
                    return data.get("test_count")
        except (OSError, json.JSONDecodeError) as e:
            print(f"Warning: Could not read state file: {e}")
        return None

    @classmethod
    def update_stored_test_count(cls, count: int) -> None:
        """Update the stored test count if the new count is greater."""
        try:
            data = {}
            if cls.STATE_FILE_PATH.exists():
                with open(cls.STATE_FILE_PATH) as f:
                    data = json.load(f)

            # Only update if the new count is greater
            if count > data.get("test_count", 0):
                data["test_count"] = count
                data["last_updated"] = str(Path(__file__).stat().st_mtime)

                with open(cls.STATE_FILE_PATH, "w") as f:
                    json.dump(data, f, indent=2)

        except (OSError, json.JSONDecodeError) as e:
            print(f"Warning: Could not update state file: {e}")

    def test_test_suite_protection(self):
        """Test that the test suite count has not decreased."""
        # Get current test count by collecting all tests
        test_count = self._collect_test_count()

        # Get stored test count
        stored_count = self.get_stored_test_count()

        print("\n=== Test Suite Protection Results ===")
        print(f"Current test count: {test_count}")
        print(
            f"Stored test count: {stored_count if stored_count is not None else 'Not set'}"
        )

        if stored_count is not None:
            difference = test_count - stored_count
            print(f"Difference: {difference:+d}")

            if difference < 0:
                pytest.fail(
                    f"Test suite regression detected! "
                    f"Current count ({test_count}) is less than stored count ({stored_count}). "
                    f"This indicates that {abs(difference)} test(s) have been removed."
                )
            elif difference > 0:
                print(
                    f"+ Test suite grew by {difference} test(s) - updating stored count"
                )
                self.update_stored_test_count(test_count)
            else:
                print("+ Test suite count unchanged")
        else:
            print(f"+ No stored count found - initializing with {test_count}")
            self.update_stored_test_count(test_count)

    def _collect_test_count(self) -> int:
        """Collect and count all pytest tests using subprocess."""
        try:
            # Get project root
            project_root = Path(__file__).parent.parent

            # Run pytest collection with minimal configuration to avoid circular imports
            env = os.environ.copy()
            env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "--collect-only",
                    "-p",
                    "no:cacheprovider",
                ],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )

            if result.returncode == 0:
                # Combine stdout and stderr for robust parsing
                combined_output = result.stdout + "\n" + result.stderr

                # Primary method: Use regex to find "collected X items"
                match = re.search(r"collected (\d+) items", combined_output)
                if match:
                    count = int(match.group(1))
                    print(f"Parsed test count from pytest summary: {count}")
                    return count

                # Fallback: count test items from the collection output
                test_count = 0
                for line in combined_output.split("\n"):
                    if (
                        "<Function" in line
                        and "test_" in line
                        or "<Coroutine" in line
                        and "test_" in line
                        or "<TestCaseFunction" in line
                        and "test_" in line
                    ):
                        test_count += 1

                if test_count > 0:
                    print(f"Parsed test count from collection output: {test_count}")
                    return test_count

            # Fallback: count test functions in Python files
            return self._count_test_files_manually()

        except Exception as e:
            print(f"Warning: Could not collect tests via subprocess: {e}")
            return self._count_test_files_manually()

    def _count_test_files_manually(self) -> int:
        """Manual fallback: count test functions in test files."""
        test_count = 0
        tests_dir = Path(__file__).parent

        for test_file in tests_dir.rglob("test_*.py"):
            if (
                test_file.is_file()
                and test_file.name != "test_meta_test_suite_protection.py"
            ):
                try:
                    with open(test_file, encoding="utf-8") as f:
                        content = f.read()
                        # Count function definitions that start with 'test_'
                        test_functions = re.findall(
                            r"^\s*(async\s+)?def\s+(test_[a-zA-Z_]\w*)\s*\(",
                            content,
                            re.MULTILINE,
                        )
                        test_count += len(test_functions)
                except Exception:
                    continue

        return test_count
