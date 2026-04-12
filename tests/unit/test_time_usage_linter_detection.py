"""Unit tests for time usage scanner detection (unguarded real-time reads)."""

from __future__ import annotations

import ast
from pathlib import Path

from tests.unit.support.time_usage_linter_scanner import TimeUsageScanner
from tests.utils.time_policy import load_allowlist


def test_scanner_detects_datetime_now(tmp_path: Path) -> None:
    """Test that scanner detects unguarded datetime.now() calls."""
    sample = """\
from datetime import datetime

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

    assert len(scanner.findings) == 1
    assert scanner.findings[0].rule == "TIME001"
    assert "datetime.now()" in scanner.findings[0].message


def test_scanner_detects_datetime_utcnow(tmp_path: Path) -> None:
    """Test that scanner detects unguarded datetime.utcnow() calls."""
    sample = """\
from datetime import datetime

def test_example():
    now = datetime.utcnow()
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

    assert len(scanner.findings) == 1
    assert scanner.findings[0].rule == "TIME001"
    assert "datetime.utcnow()" in scanner.findings[0].message


def test_scanner_detects_datetime_datetime_utcnow(tmp_path: Path) -> None:
    """Test that scanner detects unguarded datetime.datetime.utcnow() calls."""
    sample = """\
import datetime

def test_example():
    now = datetime.datetime.utcnow()
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

    assert len(scanner.findings) == 1
    assert scanner.findings[0].rule == "TIME001"
    assert "datetime.utcnow()" in scanner.findings[0].message


def test_scanner_detects_datetime_now_with_timezone(tmp_path: Path) -> None:
    """Test that scanner detects datetime.now() calls with timezone arguments."""
    sample = """\
from datetime import datetime, timezone

def test_example():
    now = datetime.now(timezone.utc)
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

    assert len(scanner.findings) == 1
    assert scanner.findings[0].rule == "TIME001"
    assert "datetime.now()" in scanner.findings[0].message


def test_scanner_detects_time_time(tmp_path: Path) -> None:
    """Test that scanner detects unguarded time.time() calls."""
    sample = """\
import time

def test_example():
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

    assert len(scanner.findings) == 1
    assert scanner.findings[0].rule == "TIME003"
    assert "time.time()" in scanner.findings[0].message


def test_scanner_detects_import_alias_time(tmp_path: Path) -> None:
    """Test that scanner detects time.time() via import alias."""
    sample = """\
from time import time

def test_example():
    now = time()
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

    assert len(scanner.findings) == 1
    assert scanner.findings[0].rule == "TIME003"


def test_import_alias_datetime_as_dt(tmp_path: Path) -> None:
    """Test detection of datetime.now() via import alias 'datetime as dt'."""
    sample = """\
from datetime import datetime as dt

def test_example():
    now = dt.now()
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

    assert len(scanner.findings) == 1
    assert scanner.findings[0].rule == "TIME001"


def test_import_alias_time_as_now_s(tmp_path: Path) -> None:
    """Test detection of time.time() via import alias 'from time import time as now_s'."""
    sample = """\
from time import time as now_s

def test_example():
    epoch = now_s()
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

    assert len(scanner.findings) == 1
    assert scanner.findings[0].rule == "TIME003"


def test_actionable_reporting_includes_file_line_column(tmp_path: Path) -> None:
    """Test that findings include accurate file paths, line numbers, and column numbers."""
    sample = """\
from datetime import datetime

def test_example():
    # Some comment
    now = datetime.now()  # Line 5, column 9
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

    assert len(scanner.findings) == 1
    finding = scanner.findings[0]
    # File path should contain the filename (may be absolute or relative)
    assert "test_sample.py" in finding.file.replace("\\", "/")
    assert finding.line == 5  # Line number of datetime.now() call
    assert finding.column >= 0  # Column offset should be valid
    assert finding.rule == "TIME001"
    assert "datetime.now()" in finding.message


def test_datetime_datetime_now_pattern(tmp_path: Path) -> None:
    """Test detection of datetime.datetime.now() pattern."""
    sample = """\
import datetime

def test_example():
    now = datetime.datetime.now()
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

    assert len(scanner.findings) == 1
    assert scanner.findings[0].rule == "TIME001"


def test_date_today_pattern(tmp_path: Path) -> None:
    """Test detection of date.today() pattern."""
    sample = """\
from datetime import date

def test_example():
    today = date.today()
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

    assert len(scanner.findings) == 1
    assert scanner.findings[0].rule == "TIME002"
    assert "date.today()" in scanner.findings[0].message
