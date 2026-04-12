from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.stall_linter.engine import _iter_stall_lint_files_for_targets


@pytest.fixture(scope="session")
def stall_lint_target_files(request: pytest.FixtureRequest) -> list[Path]:
    repo_root = Path(__file__).resolve().parents[3]
    raw_targets = request.config.getoption("stall_lint_files")
    if not isinstance(raw_targets, list):
        return []

    targets = [entry for entry in raw_targets if isinstance(entry, str)]
    if not targets:
        return []
    return _iter_stall_lint_files_for_targets(repo_root, targets)
