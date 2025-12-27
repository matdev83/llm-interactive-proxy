import ast
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
    repo_root / ".pre-commit-hooks" / "architectural-check.py",
    repo_root / "src" / "core" / "simulation" / "cli.py",
    repo_root / "src" / "core" / "simulation" / "output_utils.py",
}


def _calculate_directory_hash(directory: pathlib.Path) -> str:
    """Fast directory hash using mtime and size samples for cache invalidation.

    Optimized version that samples files instead of scanning all, avoiding full file reads.
    """
    import hashlib

    hasher = hashlib.md5()

    try:
        dir_stat = directory.stat()
        hasher.update(f"{directory}:{dir_stat.st_size}:{dir_stat.st_mtime}".encode())
    except OSError:
        pass

    py_files = list(directory.rglob("*.py"))
    sample_size = min(50, len(py_files))
    step = max(1, len(py_files) // sample_size) if py_files else 1

    for i, py_file in enumerate(py_files):
        if i % step == 0:
            try:
                file_stat = py_file.stat()
                rel_path = py_file.relative_to(directory)
                file_data = f"{rel_path}:{file_stat.st_size}:{file_stat.st_mtime}"
                hasher.update(file_data.encode())
            except OSError:
                continue

    return hasher.hexdigest()


@pytest.fixture(scope="session")
def print_check_cache() -> dict[str, Any]:
    """Session-scoped cache that pre-computes all print statement checks."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]

    cache_dir = repo_root / ".pytest_cache"
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / "no_prints_cache_v2.json"

    src_dir = repo_root / "src"
    src_hash = _calculate_directory_hash(src_dir) if src_dir.exists() else ""

    cache: dict[str, Any] = {}
    if cache_file.exists():
        try:
            with open(cache_file, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            cache = {}

    current_time = time.time()
    cache_timeout = 3600

    if (
        cache.get("src_hash") == src_hash
        and current_time - cache.get("timestamp", 0) < cache_timeout
        and "files_checked" in cache
    ):
        cached_dict: dict[str, Any] = cache["files_checked"]
        return cached_dict

    if not src_dir.exists():
        search_paths = [repo_root]
    else:
        search_paths = [src_dir]

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

    files_checked: dict[str, Any] = {}

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

            try:
                source = path.read_text()
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

                files_checked[path_str] = {
                    "mtime": file_mtime,
                    "has_print": has_print,
                    "line_no": print_line,
                }
            except (SyntaxError, ValueError):
                continue

    result = {
        "src_hash": src_hash,
        "timestamp": current_time,
        "files_checked": files_checked,
    }

    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
    except OSError:
        pass

    result_dict: dict[str, Any] = files_checked
    return result_dict


def test_no_print_statements(print_check_cache: dict[str, Any]) -> None:
    for path_str, result in print_check_cache.items():
        if result.get("has_print", False):
            raise AssertionError(
                f"print() found in {path_str} at line {result['line_no']}"
            )
