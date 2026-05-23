"""
Meta test to protect against test suite regression.

This test ensures that the number of tests in the suite does not decrease
over time, which would indicate that tests have been removed.

Note to LLM agents: You are **NOT ALLOWED** to skip, disable, mute or alter this test unless EXPLICITLY INSTRUCTED BY HUMAN OPERATOR.
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

    STATE_FILE_PATH = (
        Path(__file__).parent.parent / "var" / "state" / "test_suite_state.json"
    )

    EXPECTED_MIN_COUNT = 3706

    @classmethod
    def get_stored_test_count(cls) -> int | None:
        """Get the stored test count from the state file."""
        try:
            if cls.STATE_FILE_PATH.exists():
                with open(cls.STATE_FILE_PATH) as f:
                    data = json.load(f)
                    test_count = data.get("test_count")
                    if isinstance(test_count, int):
                        return test_count
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

    @pytest.mark.skip(reason="Skipped by default")
    def test_test_suite_protection(self):
        """Test that the test suite count has not decreased."""
        # Get current test count by collecting all tests
        test_count = self._collect_test_count()

        if test_count < self.EXPECTED_MIN_COUNT:
            pytest.fail(
                "Test suite regression detected! "
                f"Current count ({test_count}) is less than expected minimum "
                f"({self.EXPECTED_MIN_COUNT}). "
                "This indicates that tests may have been removed."
            )

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
                    f"Do not NEVER EVER, try to mute this message or disable this check."
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
        """Collect and count all pytest tests using subprocess with caching."""
        # Get project root
        project_root = Path(__file__).parent.parent

        # Check cache first - use a cache file based on test file modification times
        cache_file = self.STATE_FILE_PATH.parent / "test_collection_cache.json"
        cache_valid = False
        cached_count = None

        if cache_file.exists():
            try:
                with open(cache_file) as f:
                    cache_data = json.load(f)
                    # Check if cache is still valid by comparing test directory mtime
                    tests_dir = project_root / "tests"
                    if tests_dir.exists():
                        current_mtime = tests_dir.stat().st_mtime
                        cached_mtime = cache_data.get("tests_dir_mtime", 0)
                        if current_mtime == cached_mtime:
                            cached_count = cache_data.get("test_count")
                            cache_valid = cached_count is not None
            except (OSError, json.JSONDecodeError, KeyError):
                pass

        if cache_valid and cached_count is not None:
            print(f"Using cached test count: {cached_count}")
            return cached_count

        try:
            # Run pytest collection with minimal configuration to avoid circular imports
            env = os.environ.copy()
            # Disable xdist and testmon in subprocess to avoid conflicts with parent pytest process
            env.pop("PYTEST_XDIST_WORKER", None)
            env.pop("PYTEST_CURRENT_TEST", None)

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "--collect-only",
                    "-p",
                    "no:cacheprovider",
                    "-p",
                    "no:xdist",
                    "-p",
                    "no:testmon",
                    "--override-ini",
                    "addopts=",
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

                alt_match = re.search(r"(\d+)\s+tests\s+collected", combined_output)
                if alt_match:
                    count = int(alt_match.group(1))
                    print(
                        f"Parsed test count from pytest summary (alt format): {count}"
                    )
                    return count

                # Fallback: count test items from the collection output
                test_count = 0
                for line in combined_output.split("\n"):
                    if (
                        ("<Function" in line and "test_" in line)
                        or ("<Coroutine" in line and "test_" in line)
                        or ("<TestCaseFunction" in line and "test_" in line)
                    ):
                        test_count += 1

                if test_count > 0:
                    print(f"Parsed test count from collection output: {test_count}")
                    # Cache the result
                    self._cache_test_count(test_count, project_root)
                    return test_count

            # Fallback: count test functions in Python files
            manual_count = self._count_test_files_manually()
            # Cache the result
            self._cache_test_count(manual_count, project_root)
            return manual_count

        except subprocess.TimeoutExpired:
            print("Warning: pytest collection timed out, using manual counting")
            manual_count = self._count_test_files_manually()
            self._cache_test_count(manual_count, project_root)
            return manual_count
        except Exception as e:
            print(f"Warning: Could not collect tests via subprocess: {e}")
            manual_count = self._count_test_files_manually()
            self._cache_test_count(manual_count, project_root)
            return manual_count

    def _cache_test_count(self, count: int, project_root: Path) -> None:
        """Cache the test count result."""
        try:
            cache_file = self.STATE_FILE_PATH.parent / "test_collection_cache.json"
            tests_dir = project_root / "tests"
            tests_dir_mtime = tests_dir.stat().st_mtime if tests_dir.exists() else 0

            cache_data = {
                "test_count": count,
                "tests_dir_mtime": tests_dir_mtime,
            }

            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "w") as f:
                json.dump(cache_data, f, indent=2)
        except Exception:
            # Ignore cache errors - not critical
            pass

    def _count_test_files_manually(self) -> int:
        """Manual fallback: count test functions in test files using regex."""
        import re

        test_count = 0
        tests_dir = (
            Path(__file__).parent.parent / "tests"
        )  # Look in the tests directory

        # Use regex to find test function definitions more efficiently
        test_function_pattern = re.compile(r"^\s*def\s+test_\w+", re.MULTILINE)

        for test_file in tests_dir.rglob("test_*.py"):
            if (
                test_file.is_file()
                and test_file.name != "test_meta_test_suite_protection.py"
            ):
                try:
                    with open(test_file, encoding="utf-8") as f:
                        content = f.read()
                        # Count test function definitions using regex
                        matches = test_function_pattern.findall(content)
                        test_count += len(matches)
                except (UnicodeDecodeError, OSError):
                    continue

        return test_count
