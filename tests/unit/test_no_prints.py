import ast
import json
import os
import pathlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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

    Uses os.scandir/walk instead of rglob for faster traversal on Windows.
    """
    import hashlib

    hasher = hashlib.md5()

    try:
        dir_stat = directory.stat()
        hasher.update(f"{directory}:{dir_stat.st_size}:{dir_stat.st_mtime}".encode())
    except OSError:
        pass

    py_files: list[tuple[str, os.stat_result]] = []
    for dirpath, _, filenames in os.walk(directory):
        for fn in filenames:
            if fn.endswith(".py"):
                fp = os.path.join(dirpath, fn)
                try:
                    py_files.append((fp, os.stat(fp)))
                except OSError:
                    continue

    sample_size = min(30, len(py_files))
    step = max(1, len(py_files) // sample_size) if py_files else 1

    for i, (fp, file_stat) in enumerate(py_files):
        if i % step == 0:
            try:
                rel_path = os.path.relpath(fp, directory)
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

    skip_parts = frozenset(
        (
            "tests",
            ".venv",
            "site-packages",
            ".git",
            "dev",
            "examples",
            "tools",
            "scripts",
            "stubs",
        )
    )

    paths_to_check: list[pathlib.Path] = []

    for search_path in search_paths:
        for dirpath, _, filenames in os.walk(search_path):
            if any(skip in dirpath for skip in skip_parts):
                continue
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                path = pathlib.Path(dirpath) / fn
                if path in ALLOWED_FILES:
                    continue
                paths_to_check.append(path)

    def _check_one(path: pathlib.Path) -> tuple[str, dict[str, Any]] | None:
        try:
            path_str = str(path)
            file_mtime = path.stat().st_mtime
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
            return (
                path_str,
                {"mtime": file_mtime, "has_print": has_print, "line_no": print_line},
            )
        except (SyntaxError, ValueError):
            return None

    files_checked: dict[str, Any] = {}
    max_workers = min(8, max(1, len(paths_to_check) // 8))
    if max_workers <= 1 or len(paths_to_check) < 30:
        for path in paths_to_check:
            result = _check_one(path)
            if result:
                path_str, data = result
                files_checked[path_str] = data
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_check_one, p): p for p in paths_to_check}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    path_str, data = result
                    files_checked[path_str] = data

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
