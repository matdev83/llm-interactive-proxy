"""
Test to validate that mypy type checking passes on the src directory.

This test ensures that all source code passes mypy type checking,
which is important for maintaining code quality and catching type-related
bugs early.
"""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Ensure mypy validation tests run sequentially to prevent subprocess resource conflicts
pytestmark = pytest.mark.xdist_group("mypy_validation")


def _calculate_directory_hash(directory: Path) -> str:
    """Calculate a hash of all Python files in directory for cache invalidation.

    NOTE: Do NOT rely on directory mtime alone.

    On Windows, updating files inside a directory does not reliably update the
    directory's own mtime. That can lead to stale cached results and false
    failures/passes in CI and local runs.

    This hash uses (path, size, mtime_ns) for all .py files under the directory.
    It's still cheap compared to running mypy itself, and it invalidates
    correctly when code changes.
    """
    hasher = hashlib.md5()

    try:
        for path in sorted(directory.rglob("*.py")):
            try:
                st = path.stat()
            except OSError:
                continue

            rel = str(path.relative_to(directory)).replace("\\", "/")
            hasher.update(rel.encode("utf-8"))
            hasher.update(str(st.st_size).encode("ascii"))
            hasher.update(
                str(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))).encode("ascii")
            )
    except OSError:
        # If traversal fails, fall back to the directory path.
        hasher.update(str(directory).encode("utf-8"))

    return hasher.hexdigest()


class TestMypyValidation:
    """Test class for mypy validation of source code."""

    @pytest.fixture(scope="session")
    def mypy_result(self) -> subprocess.CompletedProcess[str]:
        """Run mypy once per session and cache the result."""
        # Get the path to the src directory
        project_root = Path(__file__).parent.parent.parent
        src_path = project_root / "src"

        # Ensure src directory exists
        assert src_path.exists(), f"Source directory not found at {src_path}"
        assert src_path.is_dir(), f"Source path {src_path} is not a directory"

        # Setup cache
        cache_dir = project_root / ".pytest_cache"
        cache_dir.mkdir(exist_ok=True)
        cache_file = cache_dir / "mypy_validation_cache.json"

        # Calculate hash for cache invalidation
        src_hash = _calculate_directory_hash(src_path)

        # Load existing cache
        cache: dict[str, str | int] = {}
        if cache_file.exists():
            try:
                with open(cache_file, encoding="utf-8") as f:
                    cache = json.load(f)
            except (OSError, json.JSONDecodeError):
                cache = {}

        # Check if cache is valid
        current_time = time.time()
        cache_timeout = 3600  # 1 hour

        if (
            cache.get("src_hash") == src_hash
            and current_time - cache.get("timestamp", 0) < cache_timeout
            and "returncode" in cache
        ):
            # Cache hit - return cached result
            return subprocess.CompletedProcess(
                args=[sys.executable, "-m", "mypy"],
                returncode=cache["returncode"],
                stdout=cache.get("stdout", ""),
                stderr=cache.get("stderr", ""),
            )

        # Cache miss - run mypy
        python_exe = Path(sys.executable)

        # Run mypy on the src directory with incremental mode for caching
        try:
            result = subprocess.run(
                [
                    str(python_exe),
                    "-m",
                    "mypy",
                    str(src_path),
                    "--incremental",
                    "--platform",
                    "win32",
                ],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                cwd=project_root,
            )

            # Save to cache
            cache.update(
                {
                    "src_hash": src_hash,
                    "timestamp": current_time,
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )

            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(cache, f, indent=2)
            except OSError:
                pass

            return result
        except subprocess.TimeoutExpired:
            pytest.fail("mypy validation timed out after 5 minutes")

    def test_mypy_passes_on_src(
        self, mypy_result: subprocess.CompletedProcess[str]
    ) -> None:
        """
        Test that mypy type checking passes on the src directory.

        This test runs mypy on the src directory and fails if any
        type checking errors are detected. This helps ensure code
        quality and catches type-related issues early.

        The test uses the project's mypy.ini configuration file
        to ensure consistent type checking behavior.

        The mypy execution is cached at session level to improve performance.
        """
        # Check if mypy found any errors
        if mypy_result.returncode != 0:
            # mypy found errors, create a detailed failure message
            error_msg = (
                f"mypy type checking failed on src directory!\n\n"
                f"Exit code: {mypy_result.returncode}\n\n"
                f"STDOUT:\n{mypy_result.stdout}\n\n"
                f"STDERR:\n{mypy_result.stderr}\n\n"
                f"This indicates there are type checking errors in the source code.\n"
                f"Please run 'mypy src' locally to see the specific errors and fix them."
            )

            pytest.fail(error_msg)

        # mypy passed successfully
        # The result might still contain some output (like notes/warnings)
        # but as long as the return code is 0, we consider it passed
        assert (
            mypy_result.returncode == 0
        ), f"mypy failed with unexpected return code: {mypy_result.returncode}"

    def test_mypy_config_exists(self) -> None:
        """
        Test that mypy configuration exists in pyproject.toml.

        This ensures that the mypy validation is using the correct
        configuration for the project.
        """
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"

        assert pyproject_path.exists(), f"pyproject.toml not found at {pyproject_path}"
        assert (
            pyproject_path.is_file()
        ), f"pyproject.toml at {pyproject_path} is not a file"

        # Verify it contains mypy configuration
        content = pyproject_path.read_text()
        assert (
            "[tool.mypy]" in content
        ), "mypy configuration not found in pyproject.toml"
        assert len(content.strip()) > 0, "pyproject.toml appears to be empty"
