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
    repo_root / "src" / "core" / "simulation" / "cli.py",  # CLI tool for simulation
    repo_root
    / "src"
    / "core"
    / "simulation"
    / "output_utils.py",  # Console output utilities
}


@pytest.fixture(scope="session")
def print_check_cache() -> dict[str, Any]:
    """Session-scoped cache that pre-computes all print statement checks."""
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

    current_time = time.time()
    cache_timeout = 3600

    # Focus only on src directory to reduce scan scope
    src_dir = repo_root / "src"
    if not src_dir.exists():
        search_paths = [repo_root]
    else:
        search_paths = [src_dir]

    # Pre-compute skip set for faster lookups
    skip_parts = {
        "tests",
        ".venv",
        "site-packages",
        ".git",
        "dev",
        "examples",
        "tools",
        "scripts",
        "stubs",
    }

    updated_cache = False

    for search_path in search_paths:
        for path in search_path.rglob("*.py"):
            if any(skip_part in path.parts for skip_part in skip_parts):
                continue
            if path in ALLOWED_FILES:
                continue
            if not path.is_file():
                continue

            path_str = str(path)
            file_mtime = path.stat().st_mtime

            if (
                path_str in cache
                and cache[path_str].get("mtime", 0) == file_mtime
                and current_time - cache[path_str].get("timestamp", 0) < cache_timeout
            ):
                continue

            try:
                source = path.read_text()
                file_hash = hashlib.sha256(source.encode()).hexdigest()

                if (
                    path_str in cache
                    and cache[path_str].get("hash") == file_hash
                    and current_time - cache[path_str].get("timestamp", 0)
                    < cache_timeout
                ):
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

                cache[path_str] = {
                    "hash": file_hash,
                    "mtime": file_mtime,
                    "timestamp": current_time,
                    "has_print": has_print,
                    "line_no": print_line,
                }
                updated_cache = True
            except (SyntaxError, ValueError):
                continue

    if updated_cache:
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2)
        except OSError:
            pass

    return cache


def test_no_print_statements(print_check_cache: dict[str, Any]) -> None:
    for path_str, result in print_check_cache.items():
        if result.get("has_print", False):
            raise AssertionError(
                f"print() found in {path_str} at line {result['line_no']}"
            )
