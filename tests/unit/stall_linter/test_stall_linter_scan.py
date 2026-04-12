from __future__ import annotations

from pathlib import Path

import pytest

import tests.unit.stall_linter.engine as stall_linter_engine
from tests.unit.stall_linter.engine import (
    _STALL_LINT_CACHE_VERSION,
    LintFinding,
    _atomic_write_json,
    _compute_stall_lint_fingerprint,
    _get_findings_with_cache,
)


def test_stall_linter_recursion_patches(stall_lint_target_files: list[Path]) -> None:
    """
    Prevent test-suite stalls caused by recursive monkeypatching of time/sleep.

    We've had real hangs from patterns like:
      - patch("asyncio.sleep", return_value=asyncio.sleep(0))
      - patch("asyncio.sleep", side_effect=lambda ...: asyncio.sleep(0))
    """
    repo_root = Path(__file__).resolve().parents[3]
    if stall_lint_target_files:
        cache_path = repo_root / ".pytest_cache" / "stall_lint_cache.targets.json"
        findings = _get_findings_with_cache(
            repo_root, cache_path, files=stall_lint_target_files
        )
    else:
        cache_path = repo_root / ".pytest_cache" / "stall_lint_cache.json"
        findings = _get_findings_with_cache(repo_root, cache_path)

    assert not findings, "\n".join(
        f"{f.file}:{f.line} {f.rule} {f.message}" for f in findings
    )


def test_stall_linter_cache_hit_skips_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "tests").mkdir(parents=True)
    (repo_root / "src" / "connectors").mkdir(parents=True)
    (repo_root / "tests" / "test_sample.py").write_text("x = 1\n", encoding="utf-8")

    cache_path = repo_root / ".pytest_cache" / "stall_lint_cache.json"
    fingerprint, file_count = _compute_stall_lint_fingerprint(repo_root)
    _atomic_write_json(
        cache_path,
        {
            "version": _STALL_LINT_CACHE_VERSION,
            "fingerprint": fingerprint,
            "file_count": file_count,
            "findings": [],
        },
    )

    def _boom(
        _repo_root: Path, *, files: list[Path] | None = None
    ) -> list[LintFinding]:
        raise AssertionError("Expected cache hit; scan should not run")

    monkeypatch.setattr(stall_linter_engine, "_scan_repo_for_stalls", _boom)
    assert _get_findings_with_cache(repo_root, cache_path) == []
