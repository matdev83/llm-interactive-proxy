"""Unit tests for time usage scanner guards, markers, allow-list, and precedence."""

from __future__ import annotations

import ast
from pathlib import Path

from tests.unit.support.time_usage_linter_scanner import TimeUsageScanner
from tests.utils.time_policy import load_allowlist


def test_scanner_respects_freezegun_guard(tmp_path: Path) -> None:
    """Test that scanner does not flag calls inside freeze_time context."""
    sample = """\
from datetime import datetime
from freezegun import freeze_time

def test_example():
    with freeze_time("2020-01-01"):
        now = datetime.now()
"""
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(sample, encoding="utf-8")

    repo_root = tmp_path
    allowlist = load_allowlist()
    scanner = TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    assert len(scanner.findings) == 0


def test_scanner_respects_fake_clock_guard(tmp_path: Path) -> None:
    """Test that scanner does not flag time.time() inside FakeClockContext."""
    sample = """\
import time
from tests.utils.fake_clock import FakeClockContext

async def test_example():
    async with FakeClockContext():
        now = time.time()
"""
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(sample, encoding="utf-8")

    repo_root = tmp_path
    allowlist = load_allowlist()
    scanner = TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    assert len(scanner.findings) == 0


def test_scanner_respects_freezegun_decorator(tmp_path: Path) -> None:
    """Test that scanner respects @freeze_time decorator."""
    sample = """\
from datetime import datetime
from freezegun import freeze_time

@freeze_time("2020-01-01")
def test_example():
    now = datetime.now()
"""
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(sample, encoding="utf-8")

    repo_root = tmp_path
    allowlist = load_allowlist()
    scanner = TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    assert len(scanner.findings) == 0


def test_scanner_respects_real_time_marker(tmp_path: Path) -> None:
    """Test that scanner respects @real_time marker."""
    sample = """\
from datetime import datetime
from tests.unit.fixtures.markers import real_time

@real_time(reason="This test measures actual performance")
def test_example():
    now = datetime.now()
"""
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(sample, encoding="utf-8")

    repo_root = tmp_path
    allowlist = load_allowlist()
    scanner = TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    assert len(scanner.findings) == 0


def test_scanner_respects_allowlist_nodeid(tmp_path: Path) -> None:
    """Test that scanner respects allow-list nodeid entries."""
    sample = """\
from datetime import datetime

def test_example():
    now = datetime.now()
"""
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(sample, encoding="utf-8")

    repo_root = tmp_path
    allowlist = {
        "version": 1,
        "entries": [
            {
                "target_type": "nodeid",
                "target": "test_sample.py::test_example",
                "reason": "Test exception",
            }
        ],
    }
    scanner = TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    assert len(scanner.findings) == 0


def test_scanner_respects_allowlist_glob(tmp_path: Path) -> None:
    """Test that scanner respects allow-list glob patterns."""
    sample = """\
from datetime import datetime

def test_example():
    now = datetime.now()
"""
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(sample, encoding="utf-8")

    repo_root = tmp_path
    allowlist = {
        "version": 1,
        "entries": [
            {
                "target_type": "glob",
                "target": "test_sample.py",
                "reason": "Test exception",
            }
        ],
    }
    scanner = TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    assert len(scanner.findings) == 0


def test_scanner_rejects_real_time_marker_without_reason(tmp_path: Path) -> None:
    """Test that scanner rejects @real_time marker without reason parameter."""
    sample = """\
from datetime import datetime
import pytest

@pytest.mark.real_time
def test_example():
    now = datetime.now()
"""
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(sample, encoding="utf-8")

    repo_root = tmp_path
    allowlist = load_allowlist()
    scanner = TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    # Should detect violation because marker lacks required reason parameter
    assert len(scanner.findings) == 1
    assert scanner.findings[0].rule == "TIME001"


def test_scanner_rejects_real_time_marker_with_empty_reason(tmp_path: Path) -> None:
    """Test that scanner rejects @real_time marker with empty reason."""
    sample = """\
from datetime import datetime
from tests.unit.fixtures.markers import real_time

@real_time(reason="")
def test_example():
    now = datetime.now()
"""
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(sample, encoding="utf-8")

    repo_root = tmp_path
    allowlist = load_allowlist()
    scanner = TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    # Should detect violation because reason is empty
    assert len(scanner.findings) == 1
    assert scanner.findings[0].rule == "TIME001"


def test_scanner_rejects_real_time_marker_with_whitespace_reason(
    tmp_path: Path,
) -> None:
    """Test that scanner rejects @real_time marker with whitespace-only reason."""
    sample = """\
from datetime import datetime
from tests.unit.fixtures.markers import real_time

@real_time(reason="   ")
def test_example():
    now = datetime.now()
"""
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(sample, encoding="utf-8")

    repo_root = tmp_path
    allowlist = load_allowlist()
    scanner = TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    # Should detect violation because reason is whitespace-only
    assert len(scanner.findings) == 1
    assert scanner.findings[0].rule == "TIME001"


def test_precedence_nodeid_overrides_marker(tmp_path: Path) -> None:
    """Test that allow-list nodeid entries take precedence over @real_time marker."""
    sample = """\
from datetime import datetime
from tests.unit.fixtures.markers import real_time

@real_time(reason="This should be ignored due to nodeid precedence")
def test_example():
    now = datetime.now()
"""
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(sample, encoding="utf-8")

    repo_root = tmp_path
    allowlist = {
        "version": 1,
        "entries": [
            {
                "target_type": "nodeid",
                "target": "test_sample.py::test_example",
                "reason": "Nodeid exemption takes precedence",
            }
        ],
    }
    scanner = TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    # Should be exempted by nodeid, not marker
    assert len(scanner.findings) == 0


def test_precedence_marker_overrides_glob(tmp_path: Path) -> None:
    """Test that @real_time marker takes precedence over glob patterns."""
    sample = """\
from datetime import datetime
from tests.unit.fixtures.markers import real_time

@real_time(reason="Marker exemption takes precedence over glob")
def test_example():
    now = datetime.now()
"""
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(sample, encoding="utf-8")

    repo_root = tmp_path
    allowlist = {
        "version": 1,
        "entries": [
            {
                "target_type": "glob",
                "target": "test_sample.py",
                "reason": "This glob should not apply when marker exists",
            }
        ],
    }
    scanner = TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    # Should be exempted by marker (precedence: nodeid > marker > glob)
    # Marker takes precedence over glob patterns
    assert len(scanner.findings) == 0


def test_mixed_time_semantics_freezegun_with_unguarded_time_time(
    tmp_path: Path,
) -> None:
    """Test detection of mixed time semantics: freezegun with unguarded time.time()."""
    sample = """\
from datetime import datetime
import time
from freezegun import freeze_time

def test_example():
    with freeze_time("2020-01-01"):
        dt = datetime.now()  # This is guarded
        epoch = time.time()  # This is NOT guarded (should be flagged)
"""
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(sample, encoding="utf-8")

    repo_root = tmp_path
    allowlist = load_allowlist()
    scanner = TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    # Should detect unguarded time.time() even though datetime.now() is guarded
    assert len(scanner.findings) == 1
    assert scanner.findings[0].rule == "TIME003"
    assert "time.time()" in scanner.findings[0].message


def test_mixed_time_semantics_fake_clock_with_unguarded_datetime_now(
    tmp_path: Path,
) -> None:
    """Test detection of mixed time semantics: FakeClockContext with unguarded datetime.now()."""
    sample = """\
from datetime import datetime
import time
from tests.utils.fake_clock import FakeClockContext

async def test_example():
    async with FakeClockContext():
        epoch = time.time()  # This is guarded
        dt = datetime.now()  # This is NOT guarded (should be flagged)
"""
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(sample, encoding="utf-8")

    repo_root = tmp_path
    allowlist = load_allowlist()
    scanner = TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    # Should detect unguarded datetime.now() even though time.time() is guarded
    assert len(scanner.findings) == 1
    assert scanner.findings[0].rule == "TIME001"
    assert "datetime.now()" in scanner.findings[0].message


def test_nested_guards_freezegun(tmp_path: Path) -> None:
    """Test that nested freezegun guards work correctly."""
    sample = """\
from datetime import datetime
from freezegun import freeze_time

def test_example():
    with freeze_time("2020-01-01"):
        dt1 = datetime.now()  # Guarded by outer
        with freeze_time("2021-01-01"):
            dt2 = datetime.now()  # Guarded by inner
        dt3 = datetime.now()  # Guarded by outer
"""
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(sample, encoding="utf-8")

    repo_root = tmp_path
    allowlist = load_allowlist()
    scanner = TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    # All calls should be guarded
    assert len(scanner.findings) == 0


def test_nested_guards_fake_clock(tmp_path: Path) -> None:
    """Test that nested FakeClockContext guards work correctly."""
    sample = """\
import time
from tests.utils.fake_clock import FakeClockContext

async def test_example():
    async with FakeClockContext():
        t1 = time.time()  # Guarded by outer
        async with FakeClockContext():
            t2 = time.time()  # Guarded by inner
        t3 = time.time()  # Guarded by outer
"""
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(sample, encoding="utf-8")

    repo_root = tmp_path
    allowlist = load_allowlist()
    scanner = TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    # All calls should be guarded
    assert len(scanner.findings) == 0


def test_guard_in_helper_function(tmp_path: Path) -> None:
    """Test that guards in helper functions don't affect test function calls."""
    sample = """\
from datetime import datetime
from freezegun import freeze_time

def helper_function():
    with freeze_time("2020-01-01"):
        dt = datetime.now()  # Guarded in helper

def test_example():
    dt = datetime.now()  # NOT guarded (should be flagged)
"""
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(sample, encoding="utf-8")

    repo_root = tmp_path
    allowlist = load_allowlist()
    scanner = TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    # Should detect unguarded call in test_example
    assert len(scanner.findings) == 1
    assert scanner.findings[0].rule == "TIME001"


def test_guard_in_test_function_protects_calls(tmp_path: Path) -> None:
    """Test that guards in test function protect calls within that function."""
    sample = """\
from datetime import datetime
from freezegun import freeze_time

def test_example():
    with freeze_time("2020-01-01"):
        dt = datetime.now()  # Should be guarded
"""
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(sample, encoding="utf-8")

    repo_root = tmp_path
    allowlist = load_allowlist()
    scanner = TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    # Call should be guarded
    assert len(scanner.findings) == 0


def test_precedence_nodeid_overrides_glob(tmp_path: Path) -> None:
    """Test that allow-list nodeid entries take precedence over glob patterns."""
    sample = """\
from datetime import datetime

def test_example():
    now = datetime.now()

def test_other():
    now = datetime.now()
"""
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(sample, encoding="utf-8")

    repo_root = tmp_path
    allowlist = {
        "version": 1,
        "entries": [
            {
                "target_type": "nodeid",
                "target": "test_sample.py::test_example",
                "reason": "Nodeid exemption",
            },
            {
                "target_type": "glob",
                "target": "test_sample.py",
                "reason": "Glob exemption (should not apply to test_example due to nodeid)",
            },
        ],
    }
    scanner = TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    # test_example should be exempted by nodeid
    # test_other should be exempted by glob
    # So no findings
    assert len(scanner.findings) == 0
