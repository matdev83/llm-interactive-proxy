"""Unit tests for time usage linter two-stage cache behavior."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

import tests.unit.support.time_usage_linter_scanner as time_usage_scanner
from tests.unit.support.time_usage_linter_scanner import (
    TIME_USAGE_LINT_CACHE_VERSION,
    LintFinding,
    _atomic_write_json,
    _compute_fast_hash,
    _compute_time_usage_lint_fingerprint,
    get_findings_with_cache,
)


def test_cache_fast_hash_skips_full_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that fast hash cache hit skips full fingerprint computation and scan."""
    repo_root = tmp_path / "repo"
    (repo_root / "tests").mkdir(parents=True)
    (repo_root / "tests" / "test_sample.py").write_text(
        "from datetime import datetime\n\ndef test_example():\n    pass\n",
        encoding="utf-8",
    )

    cache_path = repo_root / ".pytest_cache" / "time_usage_lint_cache.json"
    fast_hash, file_count = _compute_fast_hash(repo_root)
    fingerprint, _ = _compute_time_usage_lint_fingerprint(repo_root)

    # Pre-populate cache with both fast_hash and fingerprint
    _atomic_write_json(
        cache_path,
        {
            "version": TIME_USAGE_LINT_CACHE_VERSION,
            "fast_hash": fast_hash,
            "fingerprint": fingerprint,
            "file_count": file_count,
            "findings": [],
        },
    )

    # Mock functions to verify they're not called
    fingerprint_called = False
    scan_called = False

    def _boom_fingerprint(_repo_root: Path) -> tuple[str, int]:
        nonlocal fingerprint_called
        fingerprint_called = True
        raise AssertionError(
            "Expected fast hash cache hit; fingerprint should not be computed"
        )

    def _boom_scan(_repo_root: Path, _allowlist: dict[str, Any]) -> list[LintFinding]:
        nonlocal scan_called
        scan_called = True
        raise AssertionError("Expected fast hash cache hit; scan should not run")

    monkeypatch.setattr(
        time_usage_scanner,
        "_compute_time_usage_lint_fingerprint",
        _boom_fingerprint,
    )
    monkeypatch.setattr(time_usage_scanner, "scan_repo_for_time_usage", _boom_scan)

    # This should return cached results without calling fingerprint or scan
    findings = get_findings_with_cache(repo_root, cache_path)

    assert findings == []
    assert (
        not fingerprint_called
    ), "Fast hash cache hit should skip fingerprint computation"
    assert not scan_called, "Fast hash cache hit should skip full scan"


def test_cache_fingerprint_skips_scan_when_content_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that fingerprint cache hit skips scan when file touched but content unchanged."""
    repo_root = tmp_path / "repo"
    (repo_root / "tests").mkdir(parents=True)
    test_file = repo_root / "tests" / "test_sample.py"
    test_file.write_text(
        "from datetime import datetime\n\ndef test_example():\n    pass\n",
        encoding="utf-8",
    )

    cache_path = repo_root / ".pytest_cache" / "time_usage_lint_cache.json"
    fast_hash_1, file_count = _compute_fast_hash(repo_root)
    fingerprint_1, _ = _compute_time_usage_lint_fingerprint(repo_root)

    # Pre-populate cache
    _atomic_write_json(
        cache_path,
        {
            "version": TIME_USAGE_LINT_CACHE_VERSION,
            "fast_hash": fast_hash_1,
            "fingerprint": fingerprint_1,
            "file_count": file_count,
            "findings": [],
        },
    )

    # Touch the file (change mtime but not content)
    time.sleep(0.01)  # Ensure mtime changes
    test_file.touch()

    # Fast hash should still match (same paths + sizes)
    fast_hash_2, _ = _compute_fast_hash(repo_root)
    assert fast_hash_2 == fast_hash_1, "Fast hash should match when content unchanged"

    # But fingerprint will differ (mtime changed)
    fingerprint_2, _ = _compute_time_usage_lint_fingerprint(repo_root)
    assert (
        fingerprint_2 != fingerprint_1
    ), "Fingerprint should differ when mtime changes"

    # Mock scan to verify it's not called
    scan_called = False

    def _boom_scan(_repo_root: Path, _allowlist: dict[str, Any]) -> list[LintFinding]:
        nonlocal scan_called
        scan_called = True
        raise AssertionError("Expected fingerprint cache hit; scan should not run")

    monkeypatch.setattr(time_usage_scanner, "scan_repo_for_time_usage", _boom_scan)

    # This should return cached results without calling scan
    # (fast hash changed triggers fingerprint check, fingerprint matches)
    findings = get_findings_with_cache(repo_root, cache_path)

    assert findings == []
    assert not scan_called, "Fingerprint cache hit should skip full scan"
