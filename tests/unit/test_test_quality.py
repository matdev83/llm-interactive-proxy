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
                    "src_hash": src_hash,
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
                "src_hash": src_hash,
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
                "src_hash": src_hash,
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
    """Session-scoped cache for black formatting check results."""
    project_root = Path(__file__).parent.parent.parent

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
            "src_hash": src_hash,
            "tests_hash": tests_hash,
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
    """Run black check on a directory and return the result."""
    # Run black check on directory
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "black",
            "--check",  # Dry run mode - don't modify files
            "--diff",  # Show diffs if files would be changed
            str(directory),
        ],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _calculate_directory_hash(directory: Path) -> str:
    """Calculate a hash of all Python files in the directory for cache invalidation."""
    hasher = hashlib.md5()

    for py_file in directory.rglob("*.py"):
        try:
            # Use file path, size, and modification time for hashing
            file_stat = py_file.stat()
            file_data = f"{py_file}:{file_stat.st_size}:{file_stat.st_mtime}"
            hasher.update(file_data.encode())
        except OSError:
            # Skip files that can't be accessed
            continue

    return hasher.hexdigest()


@pytest.mark.quality
def test_ruff_linting_on_tests() -> None:
    """Test that ruff linting passes on the tests directory.

    This test runs ruff on the tests directory in check mode (no auto-fix)
    and fails if any linting errors are detected. This helps catch subtle
    syntax errors, import issues, and code quality problems in tests.
    """
    tests_dir = Path(__file__).parent.parent

    # Run ruff check on tests directory
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-fix",  # Don't auto-fix, just report errors
            str(tests_dir),
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent.parent,  # Project root
    )

    # Check if ruff found any issues
    if result.returncode != 0:
        error_msg = (
            f"ruff linting failed on tests directory:\n{result.stdout}\n{result.stderr}"
        )
        pytest.fail(error_msg)


@pytest.mark.quality
def test_black_formatting_on_tests(black_formatting_cache: dict[str, Any]) -> None:
    """Test that black formatting is consistent on the tests directory.

    This test runs black in check mode (dry run) on the tests directory
    and fails if any files would be reformatted. This ensures consistent
    code formatting across the test suite.
    Uses session-scoped caching for better performance.
    """
    # Get the cached black result for tests directory
    tests_result = black_formatting_cache.get("tests_result", {})

    # Check if black found any files that need formatting
    if tests_result.get("returncode", 0) != 0:
        error_msg = f"black formatting check failed on tests directory:\n{tests_result.get('stdout', '')}\n{tests_result.get('stderr', '')}"
        pytest.fail(error_msg)


# Source code quality tests
@pytest.mark.quality
def test_ruff_linting_on_src() -> None:
    """Test that ruff linting passes on the src directory.

    This test runs ruff on the src directory in check mode (no auto-fix)
    and fails if any linting errors are detected. This helps catch subtle
    syntax errors, import issues, and code quality problems in the source code.
    """
    src_dir = Path(__file__).parent.parent.parent / "src"

    # Run ruff check on src directory
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-fix",  # Don't auto-fix, just report errors
            str(src_dir),
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent.parent,  # Project root
    )

    # Check if ruff found any issues
    if result.returncode != 0:
        error_msg = (
            f"ruff linting failed on src directory:\n{result.stdout}\n{result.stderr}"
        )
        pytest.fail(error_msg)


@pytest.mark.quality
def test_black_formatting_on_src(black_formatting_cache: dict[str, Any]) -> None:
    """Test that black formatting is consistent on the src directory.

    This test runs black in check mode (dry run) on the src directory
    and fails if any files would be reformatted. This ensures consistent
    code formatting across the source code.
    Uses session-scoped caching for better performance.
    """
    # Get the cached black result for src directory
    src_result = black_formatting_cache.get("src_result", {})

    # Check if black found any files that need formatting
    if src_result.get("returncode", 0) != 0:
        error_msg = f"black formatting check failed on src directory:\n{src_result.get('stdout', '')}\n{src_result.get('stderr', '')}"
        pytest.fail(error_msg)


@pytest.mark.quality
def test_vulture_dead_code_on_src() -> None:
    """Test that vulture dead code detection passes on the src directory.

    This test runs vulture to detect potentially unused/dead code in the src directory.
    It uses the existing vulture configuration and suppressions to avoid false positives.
    This helps catch truly unused code that can be safely removed.

    The test will fail if any dead code is found with confidence >= 80%.
    """
    from pathlib import Path

    try:
        import vulture  # type: ignore[import-untyped]
    except ImportError:
        pytest.skip("vulture package not available. Install with: pip install vulture")

    # Get project root and src directory
    project_root = Path(__file__).parent.parent.parent
    src_dir = project_root / "src"

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
            # Use print for warning since logger might not be available in test context
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

    # If any dead code is found, fail the test
    if unused_items:
        error_lines = []
        error_lines.append(
            f"vulture found {len(unused_items)} potentially dead code items in src/:"
        )

        # Group by file for better readability
        files: dict[str, list] = {}
        for item in unused_items:
            filename = item.filename
            if filename not in files:
                files[filename] = []
            files[filename].append(item)

        # Format results by file
        for filename, items in sorted(files.items()):
            error_lines.append(f"\n{filename}:")
            for item in sorted(items, key=lambda x: x.first_lineno):
                error_lines.append(
                    f"  Line {item.first_lineno}: {item.typ} '{item.name}' (confidence: {item.confidence}%)"
                )

        error_lines.append(
            "\nTo suppress false positives, update vulture_suppressions.ini"
        )
        error_msg = "\n".join(error_lines)
        pytest.fail(error_msg)


@pytest.mark.quality
def test_vulture_dead_code_on_src_strict() -> None:
    """Test that vulture dead code detection passes on the src directory with 100% confidence.

    This test runs vulture to detect potentially unused/dead code in the src directory
    with a strict confidence level of 100%. It uses the existing vulture configuration
    and suppressions to avoid false positives.

    The test will fail if any dead code is found with confidence >= 100%.
    This is a stricter version of the existing vulture test.
    """
    from pathlib import Path

    try:
        import vulture  # type: ignore[import-untyped]
    except ImportError:
        pytest.skip("vulture package not available. Install with: pip install vulture")

    # Get project root and src directory
    project_root = Path(__file__).parent.parent.parent
    src_dir = project_root / "src"

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
            # Use print for warning since logger might not be available in test context
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

    # If any dead code is found at 100% confidence, fail the test
    if unused_items:
        error_lines = []
        error_lines.append(
            f"vulture found {len(unused_items)} potentially dead code items in src/ at 100% confidence:"
        )

        # Group by file for better readability
        files: dict[str, list] = {}
        for item in unused_items:
            filename = item.filename
            if filename not in files:
                files[filename] = []
            files[filename].append(item)

        # Format results by file
        for filename, items in sorted(files.items()):
            error_lines.append(f"\n{filename}:")
            for item in sorted(items, key=lambda x: x.first_lineno):
                error_lines.append(
                    f"  Line {item.first_lineno}: {item.typ} '{item.name}' (confidence: {item.confidence}%)"
                )

        error_lines.append(
            "\nTo suppress false positives, update vulture_suppressions.ini"
        )
        error_msg = "\n".join(error_lines)
        pytest.fail(error_msg)


@pytest.mark.quality
def test_vulture_dead_code_on_src_strict_cli() -> None:
    """Test that vulture CLI finds no dead code in src directory with 100% confidence.

    This test runs the vulture command-line tool directly with --min-confidence=100
    on the src directory. It fails if vulture reports any unused code at 100% confidence.

    The test will fail if vulture exits with a non-zero code, indicating issues found.
    """
    import subprocess
    import sys
    from pathlib import Path

    # Get project root and src directory
    project_root = Path(__file__).parent.parent.parent
    src_dir = project_root / "src"
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

    # If vulture found issues (exit code 1) or had an error (exit code != 0),
    # fail the test with the output
    if result.returncode != 0:
        error_msg = (
            f"vulture (100% confidence) found issues in src/:\n"
            f"Command: {' '.join(cmd)}\n"
            f"Stdout: {result.stdout}\n"
            f"Stderr: {result.stderr}\n"
            f"Return code: {result.returncode}"
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
    architectural_linter_path = project_root / "scripts" / "architectural_linter.py"
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
