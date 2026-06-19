import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pytest

# Comprehensive Unicode emoji and symbol regex
# Includes emoticons, symbols, pictographs, transport, maps, flags, and other common symbols.
EMOJI_REGEX = re.compile(
    r"""[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002500-\U00002BEF\U00002700-\U000027BF\U00002B50\U0000200D\U00002300-\U000023FF\U000024C2-\U0001F251\U0001f926-\U0001f937\U00010000-\U0010ffff\u2640-\u2642\u2600-\u2B55\u200d\u23cf\u23e9\u231a\ufe0f\u3030]+""",
    flags=re.UNICODE,
)

# List of files to skip due to legitimate use of Unicode characters
# Paths are normalized to use forward slashes and be relative to the project root
SKIPPED_FILES = {
    os.path.normpath("src/core/testing/example_usage.py"),
    os.path.normpath("tests/example_usage.py"),
    os.path.normpath("tests/integration_demo.py"),
    os.path.normpath("tests/integration/test_anthropic_frontend_integration.py"),
    os.path.normpath("tests/integration/test_real_world_loop_detection.py"),
    os.path.normpath("tests/unit/test_di_container_usage.py"),
    os.path.normpath("tests/unit/anthropic_frontend_tests/test_anthropic_router.py"),
    os.path.normpath(
        "tests/unit/core/app/controllers/test_usage_controller_comprehensive.py",
    ),
    os.path.normpath(
        "tests/unit/core/services/test_usage_tracking_service_comprehensive.py",
    ),
    os.path.normpath("tests/unit/loop_detection/test_analyzer_comprehensive.py"),
    os.path.normpath("tests/unit/loop_detection/test_buffer_comprehensive.py"),
    os.path.normpath("tests/unit/loop_detection/test_detector_comprehensive.py"),
    os.path.normpath("tests/unit/loop_detection/test_hasher.py"),
    os.path.normpath("tests/unit/loop_detection/test_hasher_comprehensive.py"),
    os.path.normpath("tests/unit/loop_detection/test_streaming_comprehensive.py"),
    os.path.normpath("tests/unit/connectors/test_openai_codex_prompt_handling.py"),
    os.path.normpath("src/core/auth/sso/web_interface.py"),
    os.path.normpath("tests/unit/transport/fastapi/adapters/sse/test_sse_formatter.py"),
}
PY_EXT = ".py"
PYC_EXT = ".pyc"


def _check_file_for_emojis(
    file_path: Path, project_root: Path
) -> tuple[str, int, str] | None:
    """Check a single file for emojis. Returns (path, line_num, line_content) or None."""
    skip_parts = {"__pycache__"}
    if any(skip_part in file_path.parts for skip_part in skip_parts):
        return None
    relative_file_path = os.path.normpath(
        os.path.relpath(str(file_path), start=str(project_root))
    )
    if relative_file_path in SKIPPED_FILES or not file_path.is_file():
        return None
    try:
        content = file_path.read_text(encoding="utf-8")
        match = EMOJI_REGEX.search(content)
        if match:
            line_start = content.rfind("\n", 0, match.start()) + 1
            line_end = content.find("\n", match.start())
            if line_end == -1:
                line_end = len(content)
            line_content = content[line_start:line_end].strip()
            line_num = content[: match.start()].count("\n") + 1
            return (str(file_path), line_num, line_content)
    except (UnicodeDecodeError, OSError):
        pass
    return None


def find_files_with_emojis(directories: list[str]) -> list[tuple[str, int, str]]:
    """
    Scans directories for files containing Unicode emojis.

    Args:
        directories: List of directories to scan.

    Returns:
        A list of tuples, where each tuple contains the file path,
        line number, and the line of code with the emoji.
    """
    project_root = Path(__file__).resolve().parents[2]
    paths_to_check: list[Path] = []
    for directory in directories:
        for root, _, files in os.walk(directory):
            for fn in files:
                if fn.endswith(".py"):
                    p = Path(root) / fn
                    if p.is_file():
                        paths_to_check.append(p)

    files_with_emojis: list[tuple[str, int, str]] = []
    max_workers = min(4, max(1, len(paths_to_check) // 10))
    if max_workers <= 1 or len(paths_to_check) < 50:
        for file_path in paths_to_check:
            result = _check_file_for_emojis(file_path, project_root)
            if result:
                files_with_emojis.append(result)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_check_file_for_emojis, p, project_root): p
                for p in paths_to_check
            }
            for future in as_completed(futures):
                result = future.result()
                if result:
                    files_with_emojis.append(result)
    return files_with_emojis


def _calculate_directory_hash(directory: str) -> str:
    """Calculate a hash of all Python files in directory for cache invalidation.

    Uses directory mtime and samples files for faster hashing.
    """
    hasher = hashlib.md5()

    try:
        dir_stat = os.stat(directory)
        hasher.update(f"{directory}:{dir_stat.st_size}:{dir_stat.st_mtime}".encode())
    except OSError:
        pass

    try:
        py_files = []
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith(".py"):
                    py_files.append(os.path.join(root, file))

        sample_size = min(30, len(py_files))
        step = max(1, len(py_files) // sample_size) if py_files else 1

        for i, py_file in enumerate(py_files):
            if i % step == 0:
                try:
                    file_stat = os.stat(py_file)
                    rel_path = os.path.relpath(py_file, directory)
                    file_data = f"{rel_path}:{file_stat.st_size}:{file_stat.st_mtime}"
                    hasher.update(file_data.encode())
                except OSError:
                    continue
    except OSError:
        pass

    return hasher.hexdigest()


def _single_pass_scan(
    directories: list[str],
) -> tuple[dict[str, str], list[tuple[str, int, str]]]:
    """Single-pass scan: compute directory hashes AND find emoji files together."""
    project_root = Path(__file__).resolve().parents[2]
    dir_hashes: dict[str, str] = {}
    all_emojis: list[tuple[str, int, str]] = []

    for directory in directories:
        hasher = hashlib.md5()
        dir_stat_ok = False
        try:
            dir_stat = os.stat(directory)
            hasher.update(
                f"{directory}:{dir_stat.st_size}:{dir_stat.st_mtime}".encode()
            )
            dir_stat_ok = True
        except OSError:
            pass

        if dir_stat_ok:
            py_files: list[str] = []
            for root, _, files in os.walk(directory):
                for file in files:
                    if file.endswith(".py"):
                        py_files.append(os.path.join(root, file))

            sample_size = min(30, len(py_files))
            step = max(1, len(py_files) // sample_size) if py_files else 1

            for i, py_file in enumerate(py_files):
                if i % step == 0:
                    try:
                        file_stat = os.stat(py_file)
                        rel_path = os.path.relpath(py_file, directory)
                        file_data = (
                            f"{rel_path}:{file_stat.st_size}:{file_stat.st_mtime}"
                        )
                        hasher.update(file_data.encode())
                    except OSError:
                        continue

                result = _check_file_for_emojis(Path(py_file), project_root)
                if result:
                    all_emojis.append(result)

        dir_hashes[directory] = hasher.hexdigest()

    return dir_hashes, all_emojis


@pytest.fixture(scope="session")
def emoji_check_cache() -> dict[str, Any]:
    """Session-scoped cache for emoji checking."""
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    directories = [
        os.path.join(project_root, "src/core"),
        os.path.join(project_root, "src/connectors"),
    ]

    cache_dir = os.path.join(project_root, ".pytest_cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, "emoji_check_cache_v2.json")

    cache: dict[str, Any] = {}
    if os.path.exists(cache_file):
        try:
            with open(cache_file, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            cache = {}

    current_time = time.time()
    cache_timeout = 3600

    quick_hashes = {d: _calculate_directory_hash(d) for d in directories}

    if (
        cache.get("dir_hashes") == quick_hashes
        and current_time - cache.get("timestamp", 0) < cache_timeout
        and "files_with_emojis" in cache
    ):
        return cache

    dir_hashes, files_with_emojis = _single_pass_scan(directories)

    serialized_results = [
        {"file_path": fp, "line_num": ln, "line": line}
        for fp, ln, line in files_with_emojis
    ]

    cache.update(
        {
            "dir_hashes": dir_hashes,
            "timestamp": current_time,
            "files_with_emojis": serialized_results,
        }
    )

    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except OSError:
        pass

    return cache


def test_no_unicode_emojis_in_codebase(emoji_check_cache: dict[str, Any]) -> None:
    """
    Test that there are no Unicode emojis in codebase.
    """
    files_with_emojis = emoji_check_cache.get("files_with_emojis", [])

    if files_with_emojis:
        error_message = "Unicode emojis found in following files:\\n"
        for item in files_with_emojis:
            file_path = item["file_path"]
            line_num = item["line_num"]
            line = item["line"]
            error_message += f'  - {file_path}, line {line_num}: "{line}"\\n'
        pytest.fail(error_message)
