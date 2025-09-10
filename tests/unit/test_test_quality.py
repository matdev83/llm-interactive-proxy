"""
Test suite for code quality checks.

This module contains tests that validate code quality, architectural compliance,
and dependency integrity across the project.
"""

import subprocess
import sys
from pathlib import Path

import pytest


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
def test_black_formatting_on_tests() -> None:
    """Test that black formatting is consistent on the tests directory.

    This test runs black in check mode (dry run) on the tests directory
    and fails if any files would be reformatted. This ensures consistent
    code formatting across the test suite.
    """
    tests_dir = Path(__file__).parent.parent

    # Run black check on tests directory
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "black",
            "--check",  # Dry run mode - don't modify files
            "--diff",  # Show diffs if files would be changed
            str(tests_dir),
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent.parent,  # Project root
    )

    # Check if black found any files that need formatting
    if result.returncode != 0:
        error_msg = f"black formatting check failed on tests directory:\n{result.stdout}\n{result.stderr}"
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
def test_black_formatting_on_src() -> None:
    """Test that black formatting is consistent on the src directory.

    This test runs black in check mode (dry run) on the src directory
    and fails if any files would be reformatted. This ensures consistent
    code formatting across the source code.
    """
    src_dir = Path(__file__).parent.parent.parent / "src"

    # Run black check on src directory
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "black",
            "--check",  # Dry run mode - don't modify files
            "--diff",  # Show diffs if files would be changed
            str(src_dir),
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent.parent,  # Project root
    )

    # Check if black found any files that need formatting
    if result.returncode != 0:
        error_msg = f"black formatting check failed on src directory:\n{result.stdout}\n{result.stderr}"
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
def test_bandit_security_scan_on_src_strict() -> None:
    """Test that bandit security scanning passes on the src directory with high severity and confidence.

    This test runs bandit to detect security issues in the src directory with strict filters:
    - Only reports issues with HIGH severity
    - Only reports issues with HIGH confidence
    - Exits with failure if any such issues are found

    This helps catch critical security vulnerabilities that should be addressed immediately.
    """
    import json
    import subprocess
    import sys
    from pathlib import Path

    # Get project root and src directory
    project_root = Path(__file__).parent.parent.parent
    src_dir = project_root / "src"

    # Run bandit with high severity and high confidence filters
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
            pytest.fail(
                f"No JSON found in bandit output:\nStdout: {result.stdout}\nStderr: {result.stderr}"
            )

        json_content = stdout[json_start:]
        bandit_output = json.loads(json_content)
    except json.JSONDecodeError as e:
        pytest.fail(
            f"Failed to parse bandit JSON output: {e}\nStdout: {result.stdout}\nStderr: {result.stderr}"
        )

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
