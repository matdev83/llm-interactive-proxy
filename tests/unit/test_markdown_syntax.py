import hashlib
import json
import subprocess
import time
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


@pytest.fixture(scope="session")
def markdown_validation_cache() -> dict:
    """Session-scoped cache for markdown validation results."""
    project_root = get_project_root()

    # Setup cache directory and file
    cache_dir = project_root / ".pytest_cache"
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / "markdown_validation_cache.json"

    # Files to check
    markdown_files = [
        project_root / "README.md",
        project_root / "AGENTS.md",
        project_root / "CONTRIBUTING.md",
        project_root / "CHANGELOG.md",
    ]

    # Calculate hash of markdown files for cache invalidation
    hasher = hashlib.md5()
    for md_file in markdown_files:
        if md_file.exists():
            try:
                file_stat = md_file.stat()
                hasher.update(f"{md_file}:{file_stat.st_size}:{file_stat.st_mtime}".encode())
            except OSError:
                pass
    files_hash = hasher.hexdigest()

    # Load existing cache or create empty cache
    cache: dict = {}
    if cache_file.exists():
        try:
            with open(cache_file, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            cache = {}

    # Check if cache is valid (same file hashes and not expired)
    current_time = time.time()
    cache_timeout = 3600  # 1 hour in seconds

    if (
        cache.get("files_hash") == files_hash
        and current_time - cache.get("timestamp", 0) < cache_timeout
        and "results" in cache
    ):
        return cache

    # Run validation and cache results
    results = {}
    for md_file in markdown_files:
        if not md_file.exists():
            results[md_file.name] = {"success": False, "output": "File not found"}
            continue

        success, output = run_pymarkdown_scan(md_file)
        results[md_file.name] = {"success": success, "output": output}

    # Cache the results
    cache.update(
        {
            "files_hash": files_hash,
            "timestamp": current_time,
            "results": results,
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
def test_markdown_syntax_validation(markdown_validation_cache: dict) -> None:
    """
    Test that all documentation Markdown files have valid syntax.

    This test uses pymarkdown to validate:
    - README.md
    - AGENTS.md
    - CONTRIBUTING.md
    - CHANGELOG.md

    The test will fail if any formatting issues are detected.
    Uses session-scoped caching for better performance.
    """
    results = markdown_validation_cache.get("results", {})

    # Track all failures
    failures = []

    # Check cached results
    for filename, result in results.items():
        if not result.get("success", False):
            failures.append(f"{filename}:\n{result.get('output', '')}")

    # Report all failures together
    if failures:
        error_message = "Markdown syntax validation failed:\n\n"
        error_message += "\n\n".join(failures)
        pytest.fail(error_message)
