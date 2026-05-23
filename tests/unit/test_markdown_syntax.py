import hashlib
import json
import subprocess
import time
from pathlib import Path

import pytest


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent


def run_pymarkdown_scan_all(
    project_root: Path, markdown_files: list[Path]
) -> dict[str, dict[str, bool | str]]:
    """
    Run pymarkdown scan on multiple files in a single subprocess call.

    Args:
        project_root: Path to the project root directory.
        markdown_files: List of paths to the Markdown files to scan.

    Returns:
        Dict mapping filename to {"success": bool, "output": str}.
    """
    results: dict[str, dict[str, bool | str]] = {}
    existing_files = [f for f in markdown_files if f.exists()]
    for f in markdown_files:
        if not f.exists():
            results[f.name] = {"success": False, "output": "File not found"}

    if not existing_files:
        return results

    try:
        cmd = [
            ".venv\\Scripts\\pymarkdown.exe",
            "-d",
            "MD013,MD036,MD024,MD040,MD029,MD033,MD031,MD022,MD007",
            "scan",
        ] + [str(f) for f in existing_files]

        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
        )

        for md_file in existing_files:
            filename = md_file.name
            lines = result.stdout.strip().split("\n")
            file_issues = [l for l in lines if md_file.name in l]
            if file_issues:
                results[filename] = {"success": False, "output": "\n".join(file_issues)}
            else:
                err_lines = [
                    l for l in result.stderr.strip().split("\n") if md_file.name in l
                ]
                if err_lines:
                    results[filename] = {
                        "success": False,
                        "output": "\n".join(err_lines),
                    }
                else:
                    results[filename] = {"success": True, "output": ""}

        return results

    except subprocess.TimeoutExpired:
        for md_file in existing_files:
            results[md_file.name] = {
                "success": False,
                "output": "Pymarkdown scan timed out",
            }
        return results
    except Exception as e:
        for md_file in existing_files:
            results[md_file.name] = {
                "success": False,
                "output": f"Error running pymarkdown: {e}",
            }
        return results


@pytest.fixture(scope="session")
def markdown_validation_cache() -> dict:
    """Session-scoped cache for markdown validation results."""
    project_root = get_project_root()

    cache_dir = project_root / ".pytest_cache"
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / "markdown_validation_cache.json"

    markdown_files = [
        project_root / "README.md",
        project_root / "AGENTS.md",
        project_root / "CONTRIBUTING.md",
        project_root / "CHANGELOG.md",
    ]

    hasher = hashlib.md5()
    for md_file in markdown_files:
        if md_file.exists():
            try:
                file_stat = md_file.stat()
                hasher.update(
                    f"{md_file}:{file_stat.st_size}:{file_stat.st_mtime}".encode()
                )
            except OSError:
                pass
    files_hash = hasher.hexdigest()

    cache: dict = {}
    if cache_file.exists():
        try:
            with open(cache_file, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            cache = {}

    current_time = time.time()
    cache_timeout = 3600

    if (
        cache.get("files_hash") == files_hash
        and current_time - cache.get("timestamp", 0) < cache_timeout
        and "results" in cache
    ):
        return cache

    results = run_pymarkdown_scan_all(project_root, markdown_files)

    cache.update(
        {
            "files_hash": files_hash,
            "timestamp": current_time,
            "results": results,
        }
    )

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
