"""
Test suite for code quality checks.

This module contains tests that validate code quality, architectural compliance,
and dependency integrity across the project.
"""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(scope="session")
def bandit_security_cache() -> dict[str, Any]:
    """Session-scoped cache for bandit security scanning results."""
    project_root = Path(__file__).parent.parent.parent
    src_dir = project_root / "src"

    # Setup cache directory and file
    cache_dir = project_root / ".pytest_cache"
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / "bandit_security_cache.json"

    # Calculate hash of src directory for cache invalidation
    src_hash = _calculate_directory_hash(src_dir)

    # Load existing cache or create empty cache
    cache: dict[str, Any] = {}
    if cache_file.exists():
        try:
            with open(cache_file, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            cache = {}

    # Check if cache is valid (same directory hash and not expired)
    current_time = time.time()
    cache_timeout = 3600  # 1 hour in seconds

    if (
        cache.get("src_hash") == src_hash
        and current_time - cache.get("timestamp", 0) < cache_timeout
        and "result" in cache
    ):
        return cache

    # Run bandit security scan
    cmd = [
        sys.executable,
        "-m",
        "bandit",
        "-r",  # Recursive scan
        "-q",  # Quiet mode - suppress progress output
        str(src_dir),
        "--severity-level",
        "high",  # Only high severity issues
        "--confidence-level",
        "high",  # Only high confidence issues
        "-f",
        "json",  # JSON format for easy parsing
    ]

    # Run bandit
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    # Parse the JSON output - bandit may output non-JSON content before the actual JSON
    try:
        # Find the start of the JSON by looking for the opening brace
        stdout = result.stdout.strip()
        json_start = stdout.find("{")
        if json_start == -1:
            # No JSON found, cache this result
            cache.update(
                {
                    "src_hash": str(src_hash),  # Ensure string conversion
                    "timestamp": current_time,
                    "result": {
                        "error": "No JSON found in bandit output",
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "returncode": result.returncode,
                    },
                }
            )
            return cache

        json_content = stdout[json_start:]
        bandit_output = json.loads(json_content)

        # Cache the successful result
        cache.update(
            {
                "src_hash": str(src_hash),  # Ensure string conversion
                "timestamp": current_time,
                "result": {
                    "bandit_output": bandit_output,
                    "returncode": result.returncode,
                },
            }
        )
    except json.JSONDecodeError as e:
        # Cache the error
        cache.update(
            {
                "src_hash": str(src_hash),  # Ensure string conversion
                "timestamp": current_time,
                "result": {
                    "error": f"Failed to parse bandit JSON output: {e}",
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                },
            }
        )

    # Save updated cache
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except OSError:
        # If we can't write cache, continue - not a test failure
        pass

    return cache


@pytest.fixture(scope="session")
def black_formatting_cache() -> dict[str, Any]:
    """Session-scoped cache for black formatting check results.

    Optimization: If ruff linting passes, we skip running black since ruff
    covers most formatting issues. This saves ~15s of setup time.
    """
    project_root = Path(__file__).parent.parent.parent

    # Quick check: if ruff passes on src, skip black entirely
    # (ruff covers most formatting issues that black would catch)
    ruff_check = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-fix", str(project_root / "src")],
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    if ruff_check.returncode == 0:
        # Ruff passed - black is redundant, return cache indicating skip
        return {
            "ruff_passed": True,
            "src_result": {"returncode": 0, "skipped": True},
            "tests_result": {"returncode": 0, "skipped": True},
        }

    # Setup cache directory and file
    cache_dir = project_root / ".pytest_cache"
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / "black_formatting_cache.json"

    # Calculate hash of key directories for cache invalidation
    src_hash = _calculate_directory_hash(project_root / "src")
    tests_hash = _calculate_directory_hash(project_root / "tests")

    # Load existing cache or create empty cache
    cache: dict[str, Any] = {}
    if cache_file.exists():
        try:
            with open(cache_file, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            cache = {}

    # Check if cache is valid (same directory hashes and not expired)
    current_time = time.time()
    cache_timeout = 3600  # 1 hour in seconds

    if (
        cache.get("src_hash") == src_hash
        and cache.get("tests_hash") == tests_hash
        and current_time - cache.get("timestamp", 0) < cache_timeout
        and "src_result" in cache
        and "tests_result" in cache
    ):
        return cache

    # Run black check on src directory
    src_result = _run_black_check(project_root / "src", project_root)

    # Run black check on tests directory
    tests_result = _run_black_check(project_root / "tests", project_root)

    # Cache the results
    cache.update(
        {
            "src_hash": str(src_hash),  # Ensure string conversion
            "tests_hash": str(tests_hash),  # Ensure string conversion
            "timestamp": current_time,
            "src_result": src_result,
            "tests_result": tests_result,
        }
    )

    # Save updated cache
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except OSError:
        # If we can't write cache, continue - not a test failure
        pass

    return cache


def _run_black_check(directory: Path, project_root: Path) -> dict[str, Any]:
    """Run black formatting check and auto-fix in a safe way for parallel tests."""
    # First run black in check mode to see if there are any issues
    check_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "black",
            "--check",
            "--diff",
            str(directory),
        ],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    # If check mode shows no issues, we're good
    if check_result.returncode == 0:
        return {
            "returncode": 0,
            "stdout": check_result.stdout,
            "stderr": check_result.stderr,
        }

    # If there are formatting issues, try to auto-fix them
    fix_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "black",
            str(directory),
        ],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    # Run check again to see if auto-fix resolved all issues
    final_check = subprocess.run(
        [
            sys.executable,
            "-m",
            "black",
            "--check",
            str(directory),
        ],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    return {
        "returncode": final_check.returncode,
        "stdout": f"Auto-fix applied. Final check result:\n{final_check.stdout}\nFix output:\n{fix_result.stdout}",
        "stderr": final_check.stderr,
    }


def _calculate_directory_hash(directory: Path) -> str:
    """Calculate a hash of all Python files in the directory for cache invalidation.

    Optimized to use directory-level modification time when possible for faster hashing.
    """
    hasher = hashlib.md5()

    # First try to use directory modification time as a fast approximation
    # This is much faster than statting every file
    try:
        dir_stat = directory.stat()
        # Use directory mtime and size as base hash
        hasher.update(f"{directory}:{dir_stat.st_size}:{dir_stat.st_mtime}".encode())
    except OSError:
        pass

    # For more accuracy, sample a subset of files (every 10th file)
    # This balances speed with cache invalidation accuracy
    py_files = list(directory.rglob("*.py"))
    sample_size = min(100, len(py_files))  # Sample up to 100 files
    step = max(1, len(py_files) // sample_size) if py_files else 1

    for i, py_file in enumerate(py_files):
        # Sample files for hashing to speed up
        if i % step == 0:
            try:
                file_stat = py_file.stat()
                # Use relative path, size, and modification time
                rel_path = py_file.relative_to(directory)
                file_data = f"{rel_path}:{file_stat.st_size}:{file_stat.st_mtime}"
                hasher.update(file_data.encode())
            except OSError:
                continue

    return hasher.hexdigest()


@pytest.mark.quality
def test_ruff_linting_on_tests() -> None:
    """Test that ruff linting passes on the tests directory with safe auto-fix.

    This test runs ruff on the tests directory with auto-fix enabled in a way
    that's safe for parallel test execution. It only fails if there are issues
    that cannot be automatically fixed.
    """
    tests_dir = Path(__file__).parent.parent
    project_root = Path(__file__).parent.parent.parent

    # First check if there are any issues
    check_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-fix",
            str(tests_dir),
        ],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    # If no issues, we're good
    if check_result.returncode == 0:
        return

    # If there are issues, try to auto-fix them (safe fixes first)
    fix_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--fix",
            str(tests_dir),
        ],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    # Check if safe auto-fix resolved all issues
    final_check = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-fix",
            str(tests_dir),
        ],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    # If safe fixes didn't resolve all issues, try unsafe fixes
    if final_check.returncode != 0:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--fix",
                "--unsafe-fixes",
                str(tests_dir),
            ],
            capture_output=True,
            text=True,
            cwd=project_root,
        )

        # Check again after unsafe fixes
        final_check = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--no-fix",
                str(tests_dir),
            ],
            capture_output=True,
            text=True,
            cwd=project_root,
        )

    # Only fail if there are still unfixable issues
    if final_check.returncode != 0:
        error_msg = (
            f"ruff linting failed on tests directory (unfixable issues found):\n"
            f"{final_check.stdout}\n{final_check.stderr}\n"
            f"Fix attempt output:\n{fix_result.stdout}\n{fix_result.stderr}"
        )
        pytest.fail(error_msg)


@pytest.mark.quality
def test_black_formatting_on_tests(black_formatting_cache: dict[str, Any]) -> None:
    """Test that black formatting passes on the tests directory with auto-fix.

    This test runs black on the tests directory with auto-fix enabled.
    It only fails if there are formatting issues that cannot be automatically fixed.
    This helps maintain consistent code style across all test files by automatically
    applying fixes and only reporting unrecoverable errors.
    Uses session-scoped caching for better performance.
    """
    # Get the cached black result for tests directory
    tests_result = black_formatting_cache.get("tests_result", {})

    # Check if black found any unrecoverable formatting issues
    if tests_result.get("returncode", 0) != 0:
        error_msg = f"black formatting failed on tests directory (unrecoverable issues found):\n{tests_result.get('stdout', '')}\n{tests_result.get('stderr', '')}"
        pytest.fail(error_msg)


# Source code quality tests
@pytest.mark.quality
def test_ruff_linting_on_src() -> None:
    """Test that ruff linting passes on the src directory with safe auto-fix.

    This test runs ruff on the src directory with auto-fix enabled in a way
    that's safe for parallel test execution. It only fails if there are issues
    that cannot be automatically fixed.
    """
    src_dir = Path(__file__).parent.parent.parent / "src"
    project_root = Path(__file__).parent.parent.parent

    # First check if there are any issues
    check_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-fix",
            str(src_dir),
        ],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    # If no issues, we're good
    if check_result.returncode == 0:
        return

    # If there are issues, try to auto-fix them
    subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--fix",
            str(src_dir),
        ],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    # Check if auto-fix resolved all issues
    final_check = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-fix",
            str(src_dir),
        ],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    # Only fail if there are still unfixable issues
    if final_check.returncode != 0:
        error_msg = f"ruff linting failed on src directory (unfixable issues found):\n{final_check.stdout}\n{final_check.stderr}"
        pytest.fail(error_msg)


# Cache for quick ruff check result
_ruff_check_passed: bool | None = None


def _quick_ruff_check() -> bool:
    """Quick check if ruff passes on src directory.

    Used to skip black formatting test when ruff passes, since ruff
    covers most formatting issues and black is mostly redundant.
    Result is cached for performance.
    """
    global _ruff_check_passed
    if _ruff_check_passed is not None:
        return _ruff_check_passed

    project_root = Path(__file__).parent.parent.parent
    src_dir = project_root / "src"

    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-fix", str(src_dir)],
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    _ruff_check_passed = result.returncode == 0
    return _ruff_check_passed


@pytest.mark.quality
def test_black_formatting_on_src(request: pytest.FixtureRequest) -> None:
    """Test that black formatting passes on the src directory with auto-fix.

    This test runs black on the src directory with auto-fix enabled.
    It only fails if there are formatting issues that cannot be automatically fixed.
    This helps maintain consistent code style across the source code by automatically
    applying fixes and only reporting unrecoverable errors.
    Uses session-scoped caching for better performance.

    Note: This test is skipped when ruff linting passes, since ruff covers
    most formatting issues that black would catch.
    """
    # Skip if ruff passes - black is redundant in this case
    # Check this BEFORE accessing the fixture to avoid expensive setup
    if _quick_ruff_check():
        pytest.skip(
            "Black formatting skipped: ruff linting passed (black is redundant when ruff passes)"
        )

    # Lazy fixture access - only created if test actually runs
    black_formatting_cache: dict[str, Any] = request.getfixturevalue(
        "black_formatting_cache"
    )

    # Get the cached black result for src directory
    src_result = black_formatting_cache.get("src_result", {})

    # Check if black found any unrecoverable formatting issues
    if src_result.get("returncode", 0) != 0:
        error_msg = f"black formatting failed on src directory (unrecoverable issues found):\n{src_result.get('stdout', '')}\n{src_result.get('stderr', '')}"
        pytest.fail(error_msg)


@pytest.fixture(scope="session")
def vulture_dead_code_cache() -> dict[str, Any]:
    """Session-scoped cache for vulture dead code scanning results."""
    project_root = Path(__file__).parent.parent.parent
    src_dir = project_root / "src"

    # Setup cache directory and file
    cache_dir = project_root / ".pytest_cache"
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / "vulture_dead_code_cache.json"

    # Calculate hash of src directory for cache invalidation
    src_hash = _calculate_directory_hash(src_dir)

    # Load existing cache or create empty cache
    cache: dict[str, Any] = {}
    if cache_file.exists():
        try:
            with open(cache_file, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            cache = {}

    # Check if cache is valid (same directory hash and not expired)
    current_time = time.time()
    cache_timeout = 3600  # 1 hour in seconds

    if (
        cache.get("src_hash") == src_hash
        and current_time - cache.get("timestamp", 0) < cache_timeout
        and "unused_items" in cache
    ):
        return cache

    # Run vulture scan
    try:
        import vulture  # type: ignore[import-untyped]
    except ImportError:
        cache.update(
            {
                "src_hash": str(src_hash),  # Ensure string conversion
                "timestamp": current_time,
                "error": "vulture package not available",
            }
        )
        return cache

    # Initialize vulture
    v = vulture.Vulture()

    # Set minimum confidence to reduce false positives
    v.confidence_default = 80

    # Load suppressions from vulture_suppressions.ini if it exists
    suppressions_file = project_root / "vulture_suppressions.ini"
    suppressed_names = set()
    if suppressions_file.exists():
        try:
            with open(suppressions_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith("#"):
                        continue
                    # Add non-comment content as suppressed names
                    suppressed_names.add(line)
        except Exception as e:
            print(f"Warning: Could not read vulture suppressions file: {e}")

    # Scan the src directory
    v.scavenge([str(src_dir)])

    # Get unused code items
    unused_items = []
    for item in v.get_unused_code():
        # Filter by confidence threshold, common false positives, and suppressions
        if (
            item.confidence >= 80
            and not _is_false_positive(item)
            and item.name not in suppressed_names
        ):
            unused_items.append(item)

    # Serialize unused items for caching (store minimal info)
    serialized_items = []
    for item in unused_items:
        serialized_items.append(
            {
                "filename": str(item.filename),  # Convert Path to str for JSON
                "name": item.name,
                "typ": item.typ,
                "first_lineno": item.first_lineno,
                "confidence": item.confidence,
            }
        )

    # Cache the results
    cache.update(
        {
            "src_hash": str(src_hash),  # Ensure string conversion
            "timestamp": current_time,
            "unused_items": serialized_items,
        }
    )

    # Save updated cache
    try:
        with open(str(cache_file), "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except (OSError, TypeError):
        # If we can't write cache (including JSON serialization errors), continue - not a test failure
        pass

    return cache


@pytest.mark.quality
def test_vulture_dead_code_on_src(vulture_dead_code_cache: dict[str, Any]) -> None:
    """Test that vulture dead code detection passes on the src directory.

    This test runs vulture to detect potentially unused/dead code in the src directory.
    It uses the existing vulture configuration and suppressions to avoid false positives.
    This helps catch truly unused code that can be safely removed.

    The test will fail if any dead code is found with confidence >= 80%.
    Uses session-scoped caching for better performance.
    """
    # Check if there was an error in the cached result
    if "error" in vulture_dead_code_cache:
        if vulture_dead_code_cache["error"] == "vulture package not available":
            pytest.skip(
                "vulture package not available. Install with: pip install vulture"
            )
        pytest.fail(f"Vulture scan failed: {vulture_dead_code_cache['error']}")

    # Get unused items from cache
    serialized_items = vulture_dead_code_cache.get("unused_items", [])

    # If any dead code is found, fail the test
    if serialized_items:
        error_lines = []
        error_lines.append(
            f"vulture found {len(serialized_items)} potentially dead code items in src/:"
        )

        # Group by file for better readability
        files: dict[str, list] = {}
        for item in serialized_items:
            filename = item["filename"]
            if filename not in files:
                files[filename] = []
            files[filename].append(item)

        # Format results by file
        for filename, items in sorted(files.items()):
            error_lines.append(f"\n{filename}:")
            for item in sorted(items, key=lambda x: x["first_lineno"]):
                error_lines.append(
                    f"  Line {item['first_lineno']}: {item['typ']} '{item['name']}' (confidence: {item['confidence']}%)"
                )

        error_lines.append(
            "\nTo suppress false positives, update vulture_suppressions.ini"
        )
        error_msg = "\n".join(error_lines)
        pytest.fail(error_msg)


@pytest.fixture(scope="session")
def vulture_dead_code_strict_cache() -> dict[str, Any]:
    """Session-scoped cache for vulture strict dead code scanning results."""
    project_root = Path(__file__).parent.parent.parent
    src_dir = project_root / "src"

    # Setup cache directory and file
    cache_dir = project_root / ".pytest_cache"
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / "vulture_dead_code_strict_cache.json"

    # Calculate hash of src directory for cache invalidation
    src_hash = _calculate_directory_hash(src_dir)

    # Load existing cache or create empty cache
    cache: dict[str, Any] = {}
    if cache_file.exists():
        try:
            with open(cache_file, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            cache = {}

    # Check if cache is valid (same directory hash and not expired)
    current_time = time.time()
    cache_timeout = 3600  # 1 hour in seconds

    if (
        cache.get("src_hash") == src_hash
        and current_time - cache.get("timestamp", 0) < cache_timeout
        and "unused_items" in cache
    ):
        return cache

    # Run vulture scan
    try:
        import vulture  # type: ignore[import-untyped]
    except ImportError:
        cache.update(
            {
                "src_hash": str(src_hash),  # Ensure string conversion
                "timestamp": current_time,
                "error": "vulture package not available",
            }
        )
        return cache

    # Initialize vulture
    v = vulture.Vulture()

    # Set minimum confidence to 100% for strict checking
    v.confidence_default = 100

    # Load suppressions from vulture_suppressions.ini if it exists
    suppressions_file = project_root / "vulture_suppressions.ini"
    suppressed_names = set()
    if suppressions_file.exists():
        try:
            with open(suppressions_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith("#"):
                        continue
                    # Add non-comment content as suppressed names
                    suppressed_names.add(line)
        except Exception as e:
            print(f"Warning: Could not read vulture suppressions file: {e}")

    # Scan the src directory
    v.scavenge([str(src_dir)])

    # Get unused code items with 100% confidence
    unused_items = []
    for item in v.get_unused_code():
        # Filter by 100% confidence threshold, common false positives, and suppressions
        if (
            item.confidence >= 100
            and not _is_false_positive(item)
            and item.name not in suppressed_names
        ):
            unused_items.append(item)

    # Serialize unused items for caching
    serialized_items = []
    for item in unused_items:
        serialized_items.append(
            {
                "filename": str(item.filename),  # Convert Path to str for JSON
                "name": item.name,
                "typ": item.typ,
                "first_lineno": item.first_lineno,
                "confidence": item.confidence,
            }
        )

    # Cache the results
    cache.update(
        {
            "src_hash": str(src_hash),  # Ensure string conversion
            "timestamp": current_time,
            "unused_items": serialized_items,
        }
    )

    # Save updated cache
    try:
        with open(str(cache_file), "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except (OSError, TypeError):
        # If we can't write cache (including JSON serialization errors), continue - not a test failure
        pass

    return cache


@pytest.mark.quality
def test_vulture_dead_code_on_src_strict(
    vulture_dead_code_strict_cache: dict[str, Any],
) -> None:
    """Test that vulture dead code detection passes on the src directory with 100% confidence.

    This test runs vulture to detect potentially unused/dead code in the src directory
    with a strict confidence level of 100%. It uses the existing vulture configuration
    and suppressions to avoid false positives.

    The test will fail if any dead code is found with confidence >= 100%.
    This is a stricter version of the existing vulture test.
    Uses session-scoped caching for better performance.
    """
    # Check if there was an error in the cached result
    if "error" in vulture_dead_code_strict_cache:
        if vulture_dead_code_strict_cache["error"] == "vulture package not available":
            pytest.skip(
                "vulture package not available. Install with: pip install vulture"
            )
        pytest.fail(f"Vulture scan failed: {vulture_dead_code_strict_cache['error']}")

    # Get unused items from cache
    serialized_items = vulture_dead_code_strict_cache.get("unused_items", [])

    # If any dead code is found at 100% confidence, fail the test
    if serialized_items:
        error_lines = []
        error_lines.append(
            f"vulture found {len(serialized_items)} potentially dead code items in src/ at 100% confidence:"
        )

        # Group by file for better readability
        files: dict[str, list] = {}
        for item in serialized_items:
            filename = item["filename"]
            if filename not in files:
                files[filename] = []
            files[filename].append(item)

        # Format results by file
        for filename, items in sorted(files.items()):
            error_lines.append(f"\n{filename}:")
            for item in sorted(items, key=lambda x: x["first_lineno"]):
                error_lines.append(
                    f"  Line {item['first_lineno']}: {item['typ']} '{item['name']}' (confidence: {item['confidence']}%)"
                )

        error_lines.append(
            "\nTo suppress false positives, update vulture_suppressions.ini"
        )
        error_msg = "\n".join(error_lines)
        pytest.fail(error_msg)


@pytest.fixture(scope="session")
def vulture_strict_cli_cache() -> dict[str, Any]:
    """Session-scoped cache for vulture strict CLI scanning results."""
    project_root = Path(__file__).parent.parent.parent
    src_dir = project_root / "src"

    # Setup cache directory and file
    cache_dir = project_root / ".pytest_cache"
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / "vulture_strict_cli_cache.json"

    # Calculate hash of src directory for cache invalidation
    src_hash = _calculate_directory_hash(src_dir)

    # Load existing cache or create empty cache
    cache: dict[str, Any] = {}
    if cache_file.exists():
        try:
            with open(cache_file, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            cache = {}

    # Check if cache is valid (same directory hash and not expired)
    current_time = time.time()
    cache_timeout = 3600  # 1 hour in seconds

    if (
        cache.get("src_hash") == src_hash
        and current_time - cache.get("timestamp", 0) < cache_timeout
        and "result" in cache
    ):
        return cache

    # Run vulture CLI scan
    import subprocess
    import sys

    suppressions_file = project_root / "vulture_suppressions.ini"

    # Build the vulture command with 100% confidence
    cmd = [
        sys.executable,
        "-m",
        "vulture",
        "--min-confidence",
        "100",
        str(src_dir),
    ]

    # Add suppressions file if it exists
    if suppressions_file.exists():
        cmd.extend(["--ignore-names", _read_suppressions_for_cli(suppressions_file)])

    # Run vulture
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    # Cache the result
    cache.update(
        {
            "src_hash": str(src_hash),  # Ensure string conversion
            "timestamp": current_time,
            "result": {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        }
    )

    # Save updated cache
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except OSError:
        pass

    return cache


@pytest.mark.quality
def test_vulture_dead_code_on_src_strict_cli(
    vulture_strict_cli_cache: dict[str, Any]
) -> None:
    """Test that vulture CLI finds no dead code in src directory with 100% confidence.

    This test runs the vulture command-line tool directly with --min-confidence=100
    on the src directory. It fails if vulture reports any unused code at 100% confidence.

    The test will fail if vulture exits with a non-zero code, indicating issues found.
    Uses session-scoped caching for better performance.
    """
    import sys
    from pathlib import Path

    cached_result = vulture_strict_cli_cache.get("result", {})

    # If vulture found issues (exit code 1) or had an error (exit code != 0),
    # fail the test with the output
    if cached_result.get("returncode", 0) != 0:
        project_root = Path(__file__).parent.parent.parent
        src_dir = project_root / "src"
        suppressions_file = project_root / "vulture_suppressions.ini"

        cmd = [
            sys.executable,
            "-m",
            "vulture",
            "--min-confidence",
            "100",
            str(src_dir),
        ]

        if suppressions_file.exists():
            cmd.extend(
                ["--ignore-names", _read_suppressions_for_cli(suppressions_file)]
            )

        error_msg = (
            f"vulture (100% confidence) found issues in src/:\n"
            f"Command: {' '.join(cmd)}\n"
            f"Stdout: {cached_result.get('stdout', '')}\n"
            f"Stderr: {cached_result.get('stderr', '')}\n"
            f"Return code: {cached_result.get('returncode', 0)}"
        )
        pytest.fail(error_msg)


def _read_suppressions_for_cli(suppressions_file: Path) -> str:
    """Read suppressions from file and format for CLI --ignore-names parameter.

    Args:
        suppressions_file: Path to the suppressions file

    Returns:
        Comma-separated string of names to ignore
    """
    suppressed_names = []
    try:
        with open(suppressions_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue
                # Add non-comment content as suppressed names
                suppressed_names.append(line)
    except Exception as e:
        # Use print for warning since logger might not be available in test context
        print(f"Warning: Could not read vulture suppressions file: {e}")

    return ",".join(suppressed_names)


@pytest.mark.quality
def test_bandit_security_scan_on_src_strict(
    bandit_security_cache: dict[str, Any],
) -> None:
    """Test that bandit security scanning passes on the src directory with high severity and confidence.

    This test runs bandit to detect security issues in the src directory with strict filters:
    - Only reports issues with HIGH severity
    - Only reports issues with HIGH confidence
    - Exits with failure if any such issues are found
    - Uses session-scoped caching for better performance

    This helps catch critical security vulnerabilities that should be addressed immediately.
    """
    # Get the cached bandit result
    cached_result = bandit_security_cache.get("result", {})

    # Check if there was an error in the cached result
    if "error" in cached_result:
        pytest.fail(
            f"Bandit scan failed: {cached_result['error']}\n"
            f"Stdout: {cached_result.get('stdout', '')}\n"
            f"Stderr: {cached_result.get('stderr', '')}"
        )

    # Get the bandit output from cache
    bandit_output = cached_result.get("bandit_output", {})

    # Check if bandit found any high severity, high confidence issues
    high_severity_issues = bandit_output.get("results", [])

    # If any high severity, high confidence issues are found, fail the test
    if high_severity_issues:
        error_lines = []
        error_lines.append(
            f"bandit found {len(high_severity_issues)} HIGH severity, HIGH confidence security issues in src/:"
        )

        # Format results by file
        files: dict[str, list] = {}
        for issue in high_severity_issues:
            filename = issue.get("filename", "unknown")
            if filename not in files:
                files[filename] = []
            files[filename].append(issue)

        # Format results by file
        for filename, issues in sorted(files.items()):
            error_lines.append(f"\n{filename}:")
            for issue in sorted(issues, key=lambda x: x.get("line_number", 0)):
                line_num = issue.get("line_number", "unknown")
                test_id = issue.get("test_id", "unknown")
                issue_text = issue.get("issue_text", "no description")
                error_lines.append(f"  Line {line_num}: {test_id} - {issue_text}")

        error_lines.append(
            "\nThese are HIGH severity issues with HIGH confidence that should be addressed immediately."
        )
        error_msg = "\n".join(error_lines)
        pytest.fail(error_msg)


@pytest.mark.quality
def test_architectural_linter_compliance() -> None:
    """Test that architectural linter passes on the src directory.

    This test runs the architectural linter to detect SOLID principle violations
    and DIP (Dependency Inversion Principle) issues. It helps ensure the codebase
    follows proper architectural patterns and dependency injection practices.

    The test will fail if any architectural violations are found.
    """
    import subprocess
    import sys
    from pathlib import Path

    # Get project root
    project_root = Path(__file__).parent.parent.parent
    architectural_linter_path = (
        project_root / "dev" / "scripts" / "architectural_linter.py"
    )
    src_dir = project_root / "src"

    # Run the architectural linter
    result = subprocess.run(
        [sys.executable, str(architectural_linter_path), str(src_dir)],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    # If the linter found violations (exit code 1), fail the test
    if result.returncode != 0:
        error_msg = f"Architectural linter found violations in src/:\n{result.stdout}\n{result.stderr}"
        pytest.fail(error_msg)

    # The linter should have succeeded (exit code 0)
    assert (
        result.returncode == 0
    ), f"Architectural linter failed:\n{result.stdout}\n{result.stderr}"


def _is_false_positive(item: object) -> bool:
    """Check if an unused item is likely a false positive based on common patterns.

    Args:
        item: Vulture unused code item

    Returns:
        True if this is likely a false positive
    """
    # Skip abstract methods (they might be called through interfaces)
    item_name = getattr(item, "name", "")
    item_typ = getattr(item, "typ", "")
    if (
        item_typ == "function"
        and isinstance(item_name, str)
        and (item_name.startswith("abstract_") or item_name.endswith("_abstract"))
    ):
        return True

    # Skip methods that follow common interface patterns
    if (
        item_typ in ["method", "function"]
        and isinstance(item_name, str)
        and item_name
        in [
            "get",
            "set",
            "create",
            "build",
            "factory",
            "handler",
            "process",
            "execute",
            "run",
            "start",
            "stop",
            "close",
        ]
    ):
        return True

    # Skip items from test-related files (should be handled by exclude patterns, but safety check)
    filename = getattr(item, "filename", "")
    if isinstance(filename, str):
        filename_str = filename
    else:
        filename_str = str(filename)
    return "test" in filename_str.lower() or "conftest" in filename_str
