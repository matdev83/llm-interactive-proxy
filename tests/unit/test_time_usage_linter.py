"""Integration entry for the time usage linter (repo-wide scan)."""

from __future__ import annotations

from pathlib import Path

from tests.unit.support.time_usage_linter_scanner import get_findings_with_cache


def test_time_usage_linter() -> None:
    """Test that no unguarded real-time reads exist in tests."""
    repo_root = Path(__file__).resolve().parents[2]
    cache_path = repo_root / ".pytest_cache" / "time_usage_lint_cache.json"
    findings = get_findings_with_cache(repo_root, cache_path)

    assert not findings, "\n".join(
        f"{f.file}:{f.line}:{f.column} {f.rule} {f.message}" for f in findings
    )
