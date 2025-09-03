import ast
import hashlib
import json
import pathlib
import time
from typing import Any

repo_root = pathlib.Path(__file__).resolve().parents[2]
ALLOWED_FILES = {
    repo_root / "src" / "main.py",
    repo_root / "dev" / "_client_call.py",
    repo_root / "tools" / "analyze_module_dependencies.py",
    repo_root / "tools" / "deprecate_legacy_endpoints.py",
    repo_root / "debug_command_test.py",
    repo_root / "debug_parsing.py",
    repo_root / ".pre-commit-hooks" / "architectural-check.py",  # Added this line
}


def test_no_print_statements() -> None:
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
    cache_timeout = 3600  # 1 hour in seconds
    updated_cache = False

    for path in repo_root.rglob("*.py"):
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
            path_str in cache
            and cache[path_str].get("mtime", 0) == file_mtime
            and current_time - cache[path_str].get("timestamp", 0) < cache_timeout
        ):
            # Use cached result
            if cache[path_str].get("has_print", False):
                raise AssertionError(
                    f"print() found in {path} at line {cache[path_str]['line_no']}"
                )
            continue

        # Analyze file
        try:
            source = path.read_text()
            file_hash = hashlib.sha256(source.encode()).hexdigest()

            # Check if we've already analyzed this exact content
            if (
                path_str in cache
                and cache[path_str].get("hash") == file_hash
                and current_time - cache[path_str].get("timestamp", 0) < cache_timeout
            ):
                if cache[path_str].get("has_print", False):
                    raise AssertionError(
                        f"print() found in {path} at line {cache[path_str]['line_no']}"
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
            cache[path_str] = {
                "hash": file_hash,
                "mtime": file_mtime,
                "timestamp": current_time,
                "has_print": has_print,
                "line_no": print_line,
            }
            updated_cache = True

            if has_print:
                raise AssertionError(f"print() found in {path} at line {print_line}")

        except (SyntaxError, ValueError):
            # Log a warning or just skip if the file is not valid Python
            # Using print here would violate our own rule, so we'll just continue
            continue

    # Save updated cache
    if updated_cache:
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2)
        except OSError:
            # If we can't write cache, just continue - not a test failure
            pass
