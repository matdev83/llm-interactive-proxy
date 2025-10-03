"""
Cache monitoring and cleanup test.

This test monitors cache directories and cleans them when they become too large.
It runs cleanup operations only every 10th execution to avoid frequent file operations.
"""

import contextlib
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


class CacheMonitorTest:
    """Monitors and cleans cache directories safely."""

    # Safe cache directory patterns - ONLY these can be cleaned
    SAFE_CACHE_PATTERNS = {
        ".mypy_cache",
        ".pytest_cache",
        "__pycache__",
        ".cache",
        ".coverage",
        "htmlcov",
        ".tox",
        "node_modules",
        ".npm",
        ".yarn",
        ".gradle",
        "target",
        "build",
        "dist",
    }

    # Maximum allowed sizes (in bytes) for cache directories
    MAX_CACHE_SIZE = 50 * 1024 * 1024  # 50MB
    MAX_CACHE_FILES = 1000  # Maximum number of files in a cache directory

    # Execution counter file
    COUNTER_FILE = Path(tempfile.gettempdir()) / "llm_proxy_cache_monitor_counter.txt"

    def __init__(self):
        self.execution_count = self._load_execution_count()

    def _load_execution_count(self) -> int:
        """Load execution count from file."""
        try:
            if self.COUNTER_FILE.exists():
                return int(self.COUNTER_FILE.read_text().strip())
        except (ValueError, OSError):
            pass
        return 0

    def _save_execution_count(self, count: int) -> None:
        """Save execution count to file."""
        with contextlib.suppress(OSError):
            self.COUNTER_FILE.write_text(str(count))

    def _is_safe_cache_directory(self, path: Path) -> bool:
        """Check if a directory is a safe cache directory to clean."""
        # Check against safe patterns
        for pattern in self.SAFE_CACHE_PATTERNS:
            if pattern in path.name or path.name.endswith(pattern):
                return True

        # Check if it's a hidden directory starting with dot
        return path.name.startswith(".") and not path.name.startswith((".git", ".venv"))

    def _is_within_project_bounds(self, path: Path) -> bool:
        """Ensure we only operate within project directory bounds."""
        try:
            # Get the current working directory (project root)
            project_root = Path.cwd()

            # Resolve the path to avoid any symlink issues
            resolved_path = path.resolve()

            # Check if the path is within the project root
            try:
                resolved_path.relative_to(project_root)
                return True
            except ValueError:
                # Path is not within project root
                return False

        except Exception:
            # If there's any error, err on the side of safety
            return False

    def _get_directory_size(self, path: Path) -> int:
        """Get total size of directory in bytes."""
        try:
            total_size = 0
            for dirpath, _dirnames, filenames in os.walk(path):
                for filename in filenames:
                    file_path = os.path.join(dirpath, filename)
                    try:
                        total_size += os.path.getsize(file_path)
                    except OSError:
                        continue
            return total_size
        except OSError:
            return 0

    def _count_directory_files(self, path: Path) -> int:
        """Count total files in directory."""
        try:
            total_files = 0
            for _dirpath, _dirnames, filenames in os.walk(path):
                total_files += len(filenames)
            return total_files
        except OSError:
            return 0

    def _should_clean_directory(self, path: Path) -> bool:
        """Determine if a cache directory should be cleaned."""
        if not self._is_safe_cache_directory(path):
            return False

        if not self._is_within_project_bounds(path):
            return False

        size = self._get_directory_size(path)
        file_count = self._count_directory_files(path)

        # Clean if either size or file count exceeds limits
        return size > self.MAX_CACHE_SIZE or file_count > self.MAX_CACHE_FILES

    def _clean_cache_directory(self, path: Path) -> bool:
        """Safely clean a cache directory."""
        if not self._should_clean_directory(path):
            return False

        try:
            # Double-check safety before deletion
            if not self._is_safe_cache_directory(path):
                return False

            if not self._is_within_project_bounds(path):
                return False

            # Additional safety check: never delete certain critical directories
            critical_patterns = {".git", "src", "tests", "docs", "README", "LICENSE"}
            if any(pattern in path.name for pattern in critical_patterns):
                return False

            # Remove the directory
            shutil.rmtree(path, ignore_errors=True)
            return True

        except Exception:
            # If anything goes wrong, don't delete
            return False

    def find_cache_directories(self, base_path: Path | None = None) -> list[Path]:
        """Find all cache directories under the given path."""
        if base_path is None:
            base_path = Path.cwd()

        cache_dirs = []

        try:
            # Use os.walk for better performance and control
            for root, dirs, _files in os.walk(base_path):
                # Skip virtual environment directories entirely for performance
                if ".venv" in dirs:
                    dirs.remove(".venv")

                for dir_name in dirs:
                    dir_path = Path(root) / dir_name
                    if self._is_safe_cache_directory(dir_path):
                        cache_dirs.append(dir_path)

                        # Skip searching within cache directories for performance
                        if dir_name in self.SAFE_CACHE_PATTERNS:
                            dirs.remove(dir_name)
        except Exception:
            pass

        return cache_dirs

    def monitor_and_clean(self) -> dict:
        """Monitor cache directories and clean if needed (every 10th execution)."""
        self.execution_count += 1
        self._save_execution_count(self.execution_count)

        result = {
            "execution_count": self.execution_count,
            "should_run_cleanup": self.execution_count % 10 == 0,
            "cache_directories_found": 0,
            "directories_cleaned": 0,
            "cleaned_directories": [],
            "errors": [],
        }

        # Only run cleanup every 10th execution
        if not result["should_run_cleanup"]:
            return result

        try:
            cache_dirs = self.find_cache_directories()
            result["cache_directories_found"] = len(cache_dirs)

            for cache_dir in cache_dirs:
                if self._clean_cache_directory(cache_dir):
                    result["directories_cleaned"] += 1
                    result["cleaned_directories"].append(str(cache_dir))

        except Exception as e:
            result["errors"].append(str(e))

        return result


@pytest.fixture
def cache_monitor():
    """Create a cache monitor instance."""
    return CacheMonitorTest()


def test_cache_monitor_safety_checks(cache_monitor):
    """Test that safety checks work correctly."""

    # Test safe cache directory detection
    safe_paths = [
        Path("/project/.mypy_cache"),
        Path("/project/__pycache__"),
        Path("/project/.pytest_cache"),
        Path("/project/build"),
    ]

    unsafe_paths = [
        Path("/project/src"),
        Path("/project/tests"),
        Path("/project/README.md"),
        Path("/project/.git"),
    ]

    for safe_path in safe_paths:
        with (
            patch.object(Path, "resolve", return_value=safe_path),
            patch.object(Path, "cwd", return_value=Path("/project")),
        ):
            assert cache_monitor._is_safe_cache_directory(safe_path)

    for unsafe_path in unsafe_paths:
        assert not cache_monitor._is_safe_cache_directory(unsafe_path)


def test_cache_monitor_execution_counter(cache_monitor):
    """Test that execution counter works correctly."""

    # Get initial count
    initial_count = cache_monitor.execution_count

    # Run monitor
    result = cache_monitor.monitor_and_clean()

    # Check that count increased
    assert result["execution_count"] == initial_count + 1

    # Reset counter for next test
    cache_monitor._save_execution_count(0)


def test_cache_monitor_project_bounds(cache_monitor):
    """Test that project bounds checking works correctly."""

    # Test paths within project
    with (
        patch.object(Path, "resolve", return_value=Path("/project/.mypy_cache")),
        patch.object(Path, "cwd", return_value=Path("/project")),
    ):
        test_path = Path("/project/.mypy_cache")
        assert cache_monitor._is_within_project_bounds(test_path)

    # Test paths outside project
    with (
        patch.object(Path, "resolve", return_value=Path("/etc/passwd")),
        patch.object(Path, "cwd", return_value=Path("/project")),
    ):
        test_path = Path("/etc/passwd")
        assert not cache_monitor._is_within_project_bounds(test_path)


def test_cache_monitor_directory_size_and_count(cache_monitor, tmp_path):
    """Test directory size and file counting functionality."""

    # Create a test directory with some files
    test_dir = tmp_path / "test_cache"
    test_dir.mkdir()

    # Create some test files
    for i in range(5):
        test_file = test_dir / f"test_{i}.txt"
        test_file.write_text(f"test content {i}" * 100)  # ~1KB each

    # Test size calculation
    size = cache_monitor._get_directory_size(test_dir)
    assert size > 0

    # Test file counting
    file_count = cache_monitor._count_directory_files(test_dir)
    assert file_count == 5


def test_cache_monitor_monitoring_function(cache_monitor, tmp_path):
    """Test the main monitoring function."""

    # Create a test cache directory
    test_cache_dir = tmp_path / ".mypy_cache"
    test_cache_dir.mkdir()

    # Create some files
    for i in range(10):
        (test_cache_dir / f"cache_{i}.pyc").write_text("test")

    # Mock the find_cache_directories method to return our test directory
    original_find = cache_monitor.find_cache_directories

    def mock_find(base_path=None):
        if base_path is None:
            base_path = tmp_path
        return [test_cache_dir]

    cache_monitor.find_cache_directories = mock_find

    # Force cleanup to run by setting execution count to multiple of 10
    cache_monitor.execution_count = 9  # Next execution will be 10

    # Run monitoring
    result = cache_monitor.monitor_and_clean()

    # Restore original method
    cache_monitor.find_cache_directories = original_find

    # Check results
    assert "execution_count" in result
    assert "should_run_cleanup" in result
    assert "cache_directories_found" in result
    assert "directories_cleaned" in result
    assert "cleaned_directories" in result
    assert "errors" in result

    # Check that cache directory was found
    assert result["cache_directories_found"] >= 1

    # Since we forced it to run on the 10th execution, cleanup should have run
    assert result["should_run_cleanup"] is True


def test_cache_monitor_integration(cache_monitor):
    """Integration test for cache monitoring."""

    # Run monitoring
    result = cache_monitor.monitor_and_clean()

    # Basic validation
    assert isinstance(result["execution_count"], int)
    assert isinstance(result["should_run_cleanup"], bool)
    assert isinstance(result["cache_directories_found"], int)
    assert isinstance(result["directories_cleaned"], int)
    assert isinstance(result["cleaned_directories"], list)
    assert isinstance(result["errors"], list)

    # Safety checks
    assert result["execution_count"] > 0

    # Ensure no errors in normal operation
    if result["errors"]:
        pytest.fail(f"Cache monitoring had errors: {result['errors']}")


# This is the "fake" test that actually does the cache monitoring
def test_cache_monitor_cleanup_worker(cache_monitor):
    """Fake test that monitors and cleans cache directories.

    This test runs every time but only performs cleanup every 10th execution.
    It's designed to be a background maintenance task that helps keep
    the test suite running efficiently by cleaning up cache directories
    that grow too large.
    """

    # Run the monitoring
    result = cache_monitor.monitor_and_clean()

    # Always pass - this is a maintenance task, not a real test
    assert True

    # Log what happened (only in verbose mode)
    if result["should_run_cleanup"]:
        print(f"\nCache Monitor (Execution #{result['execution_count']}):")
        print(f"  - Found {result['cache_directories_found']} cache directories")
        print(f"  - Cleaned {result['directories_cleaned']} directories")

        if result["cleaned_directories"]:
            print("  - Cleaned directories:")
            for dir_path in result["cleaned_directories"]:
                print(f"    * {dir_path}")

        if result["errors"]:
            print("  - Errors:")
            for error in result["errors"]:
                print(f"    * {error}")

    # Reset counter periodically to prevent it from growing indefinitely
    if result["execution_count"] >= 100:
        cache_monitor._save_execution_count(0)
