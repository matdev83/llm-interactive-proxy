import ast
import hashlib
import json
import pathlib
import time
from typing import Any

import pytest

repo_root = pathlib.Path(__file__).resolve().parents[2]
ALLOWED_FILES = {
    repo_root / "src" / "main.py",
    repo_root / "dev" / "_client_call.py",
    repo_root / "debug_command_test.py",
    repo_root / "debug_parsing.py",
    repo_root / ".pre-commit-hooks" / "architectural-check.py",  # Added this line
}


@pytest.fixture(scope="session")
def print_check_cache() -> dict[str, Any]:
    """Session-scoped cache for print statement checking."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]

    # Setup cache directory and file
    cache_dir = repo_root / ".pytest_cache"
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / "no_prints_cache.json"

    # Load existing cache or create empty cache
    cache: dict[str, Any] = {}
    if cache_file.exists():
        try:
            with open(cache_file, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            cache = {}

    return cache


def test_no_print_statements(print_check_cache: dict[str, Any]) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[2]

    current_time = time.time()
    cache_timeout = 3600  # 1 hour in seconds
    updated_cache = False

    # Focus only on src directory to reduce scan scope
    src_dir = repo_root / "src"
    if not src_dir.exists():
        # Fallback to full scan if src directory doesn't exist
        search_paths = [repo_root]
    else:
        search_paths = [src_dir]

    for search_path in search_paths:
        for path in search_path.rglob("*.py"):
            if (
                "tests" in path.parts
                or ".venv" in path.parts
                or "site-packages" in path.parts
                or ".git" in path.parts
                or "dev" in path.parts
                or "examples" in path.parts
                or "tools" in path.parts
                or "scripts" in path.parts
            ):
                continue
            if path in ALLOWED_FILES:
                continue
            if not path.is_file():  # Ensure it's a file, not a directory or symlink
                continue

            path_str = str(path)
            file_mtime = path.stat().st_mtime

            # Check if file is cached and still valid
            if (
                path_str in print_check_cache
                and print_check_cache[path_str].get("mtime", 0) == file_mtime
                and current_time - print_check_cache[path_str].get("timestamp", 0)
                < cache_timeout
            ):
                # Use cached result
                if print_check_cache[path_str].get("has_print", False):
                    raise AssertionError(
                        f"print() found in {path} at line {print_check_cache[path_str]['line_no']}"
                    )
                continue

            # Analyze file
            try:
                source = path.read_text()
                file_hash = hashlib.sha256(source.encode()).hexdigest()

                # Check if we've already analyzed this exact content
                if (
                    path_str in print_check_cache
                    and print_check_cache[path_str].get("hash") == file_hash
                    and current_time - print_check_cache[path_str].get("timestamp", 0)
                    < cache_timeout
                ):
                    if print_check_cache[path_str].get("has_print", False):
                        raise AssertionError(
                            f"print() found in {path} at line {print_check_cache[path_str]['line_no']}"
                        )
                    continue

                tree = ast.parse(source)
                has_print = False
                print_line = None

                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "print"
                    ):
                        has_print = True
                        print_line = node.lineno
                        break

                # Cache the result
                print_check_cache[path_str] = {
                    "hash": file_hash,
                    "mtime": file_mtime,
                    "timestamp": current_time,
                    "has_print": has_print,
                    "line_no": print_line,
                }
                updated_cache = True

                if has_print:
                    raise AssertionError(
                        f"print() found in {path} at line {print_line}"
                    )

            except (SyntaxError, ValueError):
                # Log a warning or just skip if the file is not valid Python
                # Using print here would violate our own rule, so we'll just continue
                continue

    # Save updated cache (only write if we made changes)
    if updated_cache:
        try:
            cache_file = repo_root / ".pytest_cache" / "no_prints_cache.json"
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(print_check_cache, f, indent=2)
        except OSError:
            # If we can't write cache, just continue - not a test failure
            pass
