import subprocess
from pathlib import Path

import pytest


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent


def run_pymarkdown_scan(file_path: Path) -> tuple[bool, str]:
    """
    Run pymarkdown scan on a file.

    Args:
        file_path: Path to the Markdown file to scan.

    Returns:
        A tuple of (success, output) where success is True if no issues found.
    """
    try:
        # Run pymarkdown scan command using the executable directly
        # Disable rules that are too restrictive for documentation:
        # - MD013: Line length (80 chars is too short for docs)
        # - MD036: Emphasis as heading (bold text is acceptable in docs)
        # - MD024: Duplicate headings (common in docs with repeated sections)
        # - MD040: Code fence language (not all examples need language tags)
        # - MD029: Ordered list prefix (allows flexible list numbering)
        # - MD033: Inline HTML (needed for collapsible sections, etc.)
        # - MD031: Blank lines around fences (compact formatting is acceptable)
        # - MD022: Blank lines around headings (compact formatting is acceptable)
        # - MD007: List indentation (flexible indentation is acceptable)
        result = subprocess.run(
            [
                ".venv\\Scripts\\pymarkdown.exe",
                "-d",
                "MD013,MD036,MD024,MD040,MD029,MD033,MD031,MD022,MD007",
                "scan",
                str(file_path),
            ],
            cwd=get_project_root(),
            capture_output=True,
            text=True,
            timeout=30,
        )

        # pymarkdown returns non-zero exit code if issues are found
        success = result.returncode == 0
        output = result.stdout + result.stderr

        return success, output

    except subprocess.TimeoutExpired:
        return False, "Pymarkdown scan timed out"
    except Exception as e:
        return False, f"Error running pymarkdown: {e}"


@pytest.mark.quality
def test_markdown_syntax_validation() -> None:
    """
    Test that all documentation Markdown files have valid syntax.

    This test uses pymarkdown to validate:
    - README.md
    - AGENTS.md
    - CONTRIBUTING.md
    - CHANGELOG.md

    The test will fail if any formatting issues are detected.
    """
    project_root = get_project_root()

    # Files to check
    markdown_files = [
        project_root / "README.md",
        project_root / "AGENTS.md",
        project_root / "CONTRIBUTING.md",
        project_root / "CHANGELOG.md",
    ]

    # Track all failures
    failures = []

    # Scan each file
    for md_file in markdown_files:
        # Check if file exists
        if not md_file.exists():
            failures.append(f"{md_file.name}: File not found")
            continue

        # Run pymarkdown scan
        success, output = run_pymarkdown_scan(md_file)

        if not success:
            failures.append(f"{md_file.name}:\n{output}")

    # Report all failures together
    if failures:
        error_message = "Markdown syntax validation failed:\n\n"
        error_message += "\n\n".join(failures)
        pytest.fail(error_message)
