"""
Meta test to detect duplicate test file names.

This test ensures that there are no duplicate test file names across the test suite,
which can cause pytest collection issues and test interference.

When Git is available and the project root is a Git work tree, only **tracked**
files under ``tests/`` are considered (CI-equivalent), so concurrent local work
with untracked ``test_*.py`` files does not create false positives.

Note to LLM agents: You are **NOT ALLOWED** to skip, disable, mute or alter this test
unless EXPLICITLY INSTRUCTED BY HUMAN OPERATOR.
"""

from __future__ import annotations

import subprocess
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

import pytest


def _is_pytest_style_test_module(name: str) -> bool:
    return name.startswith("test_") and name.endswith(".py")


def _collect_duplicates(paths: Iterable[Path]) -> dict[str, list[Path]]:
    """Map ``test_*.py`` basename -> paths; only entries with len > 1 are duplicates."""
    filename_to_paths: defaultdict[str, list[Path]] = defaultdict(list)
    for path in paths:
        name = path.name
        if _is_pytest_style_test_module(name):
            filename_to_paths[name].append(path)
    return {fn: ps for fn, ps in filename_to_paths.items() if len(ps) > 1}


def _try_list_tracked_test_py_files(project_root: Path) -> list[Path] | None:
    """
    Return paths (under ``tests/``) for tracked ``test_*.py`` files, or ``None`` if
    Git cannot be used (missing binary, not a repo, ls-files error).
    """
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(project_root),
                "ls-files",
                "-z",
                "--",
                "tests/",
            ],
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None

    if completed.returncode != 0:
        return None

    rels = completed.stdout.decode("utf-8", errors="replace").split("\0")
    out: list[Path] = []
    for rel in rels:
        if not rel:
            continue
        if not rel.startswith("tests/"):
            continue
        name = Path(rel).name
        if not _is_pytest_style_test_module(name):
            continue
        out.append(project_root / rel)
    return out


def _iter_test_py_paths_for_duplicate_scan(
    project_root: Path, tests_dir: Path
) -> list[Path]:
    """
    Prefer Git-tracked ``tests/**/test_*.py``; fall back to filesystem scan if Git
    is unavailable (e.g. source tarball without ``.git``).
    """
    tracked = _try_list_tracked_test_py_files(project_root)
    if tracked is not None:
        return tracked

    filename_paths: list[Path] = []
    for test_file in tests_dir.rglob("test_*.py"):
        if test_file.is_file():
            filename_paths.append(test_file)
    return filename_paths


def test_collect_duplicates_finds_basename_collisions() -> None:
    root = Path("dummy_root")
    paths = [root / "pkg" / "test_dup.py", root / "other" / "test_dup.py"]
    dups = _collect_duplicates(paths)
    assert list(dups.keys()) == ["test_dup.py"]
    assert len(dups["test_dup.py"]) == 2


def test_collect_duplicates_ignores_non_test_modules() -> None:
    root = Path("dummy_root")
    paths = [root / "conftest.py", root / "support.py", root / "test_ok.py"]
    dups = _collect_duplicates(paths)
    assert dups == {}


def test_no_duplicate_test_file_names() -> None:
    """
    Test that there are no duplicate test file names in the test suite.

    Under Git, only tracked files are scanned (matches CI). Otherwise all
    ``test_*.py`` files under ``tests/`` are scanned.
    """
    project_root = Path(__file__).resolve().parent.parent
    tests_dir = project_root / "tests"

    if not tests_dir.exists():
        pytest.skip("Tests directory not found")

    paths = _iter_test_py_paths_for_duplicate_scan(project_root, tests_dir)
    duplicates = _collect_duplicates(paths)

    if duplicates:
        error_lines = [
            "Duplicate test file names detected!",
            "",
            "The following test file names appear multiple times:",
            "",
        ]

        for filename, paths_list in sorted(duplicates.items()):
            error_lines.append(f"  '{filename}' found in {len(paths_list)} locations:")
            for path in sorted(paths_list, key=lambda p: str(p).lower()):
                try:
                    rel_path = path.relative_to(project_root)
                except ValueError:
                    rel_path = path
                error_lines.append(f"    - {rel_path}")

        error_message = "\n".join(error_lines)
        pytest.fail(error_message)

    assert not duplicates, "No duplicate test file names among scanned paths"
