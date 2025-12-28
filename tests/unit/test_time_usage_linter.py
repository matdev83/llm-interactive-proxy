"""Time usage linter to prevent unsafe real-time reads in tests.

This linter scans tests for unguarded calls to real system wall-clock time
APIs and fails unless explicitly exempted via @real_time marker or allow-list.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from tests.utils.time_policy import is_exempted, load_allowlist


@dataclass(frozen=True)
class LintFinding:
    """Represents a single lint finding."""

    file: str
    line: int
    column: int
    rule: str
    message: str


_TIME_USAGE_LINT_CACHE_VERSION = 1


def _iter_time_usage_lint_files(repo_root: Path) -> list[Path]:
    """Iterate over Python files in tests directory."""
    root = repo_root / "tests"
    if not root.exists():
        return []
    return sorted(root.rglob("*.py"))


def _compute_fast_hash(repo_root: Path) -> tuple[str, int]:
    """Compute fast hash of linted Python tree (paths + sizes only, no mtimes).

    This is used as the first stage of caching - if this hash matches,
    we can skip the expensive full fingerprint computation and AST scan.
    """
    hasher = hashlib.blake2b(digest_size=16)
    count = 0
    for file_path in _iter_time_usage_lint_files(repo_root):
        try:
            stat = file_path.stat()
        except OSError:
            continue

        rel = file_path.relative_to(repo_root).as_posix()
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(str(stat.st_size).encode("utf-8"))
        hasher.update(b"\0")
        count += 1

    return hasher.hexdigest(), count


def _compute_time_usage_lint_fingerprint(repo_root: Path) -> tuple[str, int]:
    """Compute full fingerprint of linted Python tree for caching (paths + sizes + mtimes).

    This is only computed if the fast hash indicates changes may have occurred.
    """
    hasher = hashlib.blake2b(digest_size=16)
    count = 0
    for file_path in _iter_time_usage_lint_files(repo_root):
        try:
            stat = file_path.stat()
        except OSError:
            continue

        rel = file_path.relative_to(repo_root).as_posix()
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(str(stat.st_size).encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(str(stat.st_mtime_ns).encode("utf-8"))
        hasher.update(b"\0")
        count += 1

    return hasher.hexdigest(), count


def _load_time_usage_lint_cache(cache_path: Path) -> dict[str, Any] | None:
    """Load cached lint results."""
    try:
        raw = cache_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return None

    try:
        data = json.loads(raw)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None
    if data.get("version") != _TIME_USAGE_LINT_CACHE_VERSION:
        return None
    return data


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomically write JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


class GuardType(str, Enum):
    """Types of guard contexts."""

    FREEZEGUN = "freezegun"
    FAKE_CLOCK = "fake_clock"


class _TimeUsageScanner(ast.NodeVisitor):
    """AST visitor to detect unguarded real-time reads in tests."""

    def __init__(
        self, *, file_path: Path, repo_root: Path, allowlist: dict[str, Any]
    ) -> None:
        """Initialize scanner.

        Args:
            file_path: Path to the file being scanned
            repo_root: Root of the repository
            allowlist: Allow-list dictionary for exemptions
        """
        self._file_path = file_path
        self._repo_root = repo_root
        self._allowlist = allowlist
        self.findings: list[LintFinding] = []

        # Track imports to detect aliases
        self._datetime_imports: set[str] = set()  # Names imported from datetime
        self._time_imports: set[str] = set()  # Names imported from time
        self._date_imports: set[str] = set()  # Names imported from date

        # Track guard contexts (stack of active guards)
        self._guard_stack: list[GuardType] = []

        # Track current test function for marker checking
        self._current_test_function: ast.FunctionDef | ast.AsyncFunctionDef | None = (
            None
        )
        self._test_functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        """Track module imports."""
        for alias in node.names:
            if alias.name == "datetime":
                # `import datetime` - track as 'datetime'
                self._datetime_imports.add("datetime")
            elif alias.name == "time":
                # `import time` - track as 'time'
                self._time_imports.add("time")
            elif alias.name == "date":
                # `import date` - track as 'date'
                self._date_imports.add("date")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        """Track from-imports to detect aliases."""
        if node.module == "datetime":
            for alias in node.names:
                name = alias.asname if alias.asname else alias.name
                self._datetime_imports.add(name)
                # Also track if date is imported from datetime
                if alias.name == "date":
                    self._date_imports.add(name)
        elif node.module == "time":
            for alias in node.names:
                name = alias.asname if alias.asname else alias.name
                self._time_imports.add(name)
        elif node.module == "date":
            for alias in node.names:
                name = alias.asname if alias.asname else alias.name
                self._date_imports.add(name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        """Track test functions and check for real_time markers and freeze_time decorators."""
        old_test = self._current_test_function
        if node.name.startswith("test_"):
            self._current_test_function = node
            self._test_functions.append(node)

        # Check for @freeze_time decorator
        if self._has_freezegun_decorator(node):
            self._guard_stack.append(GuardType.FREEZEGUN)

        self.generic_visit(node)

        if self._has_freezegun_decorator(node):
            self._guard_stack.pop()

        self._current_test_function = old_test

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        """Track async test functions and check for freeze_time decorators."""
        old_test = self._current_test_function
        if node.name.startswith("test_"):
            self._current_test_function = node
            self._test_functions.append(node)

        # Check for @freeze_time decorator
        if self._has_freezegun_decorator(node):
            self._guard_stack.append(GuardType.FREEZEGUN)

        self.generic_visit(node)

        if self._has_freezegun_decorator(node):
            self._guard_stack.pop()

        self._current_test_function = old_test

    def visit_With(self, node: ast.With) -> None:  # noqa: N802
        """Track freeze_time context managers and patch guards."""
        # Check if this is a freeze_time context
        guard_type = self._detect_freezegun_guard(node)
        if guard_type:
            self._guard_stack.append(guard_type)
        # Check if this is a patch("time.time", ...) guard
        patch_guard = self._detect_patch_guard(node)
        if patch_guard:
            self._guard_stack.append(patch_guard)
        self.generic_visit(node)
        if guard_type:
            self._guard_stack.pop()
        if patch_guard:
            self._guard_stack.pop()

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:  # noqa: N802
        """Track FakeClockContext async context managers."""
        # Check if this is a FakeClockContext
        guard_type = self._detect_fake_clock_guard(node)
        if guard_type:
            self._guard_stack.append(guard_type)
        self.generic_visit(node)
        if guard_type:
            self._guard_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        """Detect real-time read calls."""
        # Check for datetime.now(), datetime.utcnow()
        if self._is_datetime_now_call(node):
            if not self._is_guarded(GuardType.FREEZEGUN):
                self._add_datetime_violation(node)
        # Check for date.today()
        elif self._is_date_today_call(node):
            if not self._is_guarded(GuardType.FREEZEGUN):
                self._add_date_today_violation(node)
        # Check for time.time()
        elif self._is_time_time_call(node) and not self._is_guarded(
            GuardType.FAKE_CLOCK
        ):
            self._add_time_violation(node)

        self.generic_visit(node)

    def _detect_freezegun_guard(self, node: ast.With) -> GuardType | None:
        """Detect if a With node is a freeze_time guard."""
        for item in node.items:
            ctx = item.context_expr
            # Check for freeze_time(...) call
            if isinstance(ctx, ast.Call):
                func = ctx.func
                # Could be freeze_time or freezegun.freeze_time
                if isinstance(func, ast.Name) and func.id == "freeze_time":
                    return GuardType.FREEZEGUN
                if isinstance(func, ast.Attribute) and func.attr == "freeze_time":
                    return GuardType.FREEZEGUN
        return None

    def _detect_patch_guard(self, node: ast.With) -> GuardType | None:
        """Detect if a With node is a patch("time.time", ...) guard."""
        for item in node.items:
            ctx = item.context_expr
            # Check for patch(...) call
            if isinstance(ctx, ast.Call):
                func = ctx.func
                # Check for patch or unittest.mock.patch
                is_patch = (isinstance(func, ast.Name) and func.id == "patch") or (
                    isinstance(func, ast.Attribute) and func.attr == "patch"
                )

                if is_patch and len(ctx.args) > 0:
                    # Check if first argument is "time.time" or similar
                    first_arg = ctx.args[0]
                    # Check for string literal "time.time"
                    if (
                        isinstance(first_arg, ast.Constant)
                        and isinstance(first_arg.value, str)
                        and "time.time" in first_arg.value
                    ):
                        return GuardType.FAKE_CLOCK
                    # Also handle older Python versions with ast.Str
                    if isinstance(first_arg, ast.Str) and "time.time" in first_arg.s:  # type: ignore[attr-defined]
                        return GuardType.FAKE_CLOCK
        return None

    def _detect_fake_clock_guard(self, node: ast.AsyncWith) -> GuardType | None:
        """Detect if an AsyncWith node is a FakeClockContext guard."""
        for item in node.items:
            ctx = item.context_expr
            # Check for FakeClockContext(...) call
            if isinstance(ctx, ast.Call):
                func = ctx.func
                if isinstance(func, ast.Name) and func.id == "FakeClockContext":
                    return GuardType.FAKE_CLOCK
                if isinstance(func, ast.Attribute) and func.attr == "FakeClockContext":
                    return GuardType.FAKE_CLOCK
        return None

    def _has_freezegun_decorator(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> bool:
        """Check if function has @freeze_time decorator."""
        for decorator in node.decorator_list:
            # Check for @freeze_time(...) or @freezegun.freeze_time(...)
            if isinstance(decorator, ast.Call):
                func_node = decorator.func
                if isinstance(func_node, ast.Name) and func_node.id == "freeze_time":
                    return True
                if (
                    isinstance(func_node, ast.Attribute)
                    and func_node.attr == "freeze_time"
                ):
                    return True
            elif isinstance(decorator, ast.Name):
                # @freeze_time (without args)
                if decorator.id == "freeze_time":
                    return True
            elif isinstance(decorator, ast.Attribute):
                # @freezegun.freeze_time
                if decorator.attr == "freeze_time":
                    return True

        return False

    def _is_guarded(self, required_guard: GuardType) -> bool:
        """Check if current context is guarded by the required guard type."""
        return required_guard in self._guard_stack

    def _is_datetime_now_call(self, node: ast.Call) -> bool:
        """Check if call is datetime.now() or datetime.utcnow()."""
        if not isinstance(node.func, ast.Attribute):
            return False

        attr_name = node.func.attr
        if attr_name not in ("now", "utcnow"):
            return False

        # Check if the object is datetime (from imports)
        if isinstance(node.func.value, ast.Name):
            return node.func.value.id in self._datetime_imports
        # Handle datetime.datetime.now()
        return (
            isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "datetime"
            and node.func.value.attr == "datetime"
        )

    def _is_date_today_call(self, node: ast.Call) -> bool:
        """Check if call is date.today()."""
        if not isinstance(node.func, ast.Attribute):
            return False

        if node.func.attr != "today":
            return False

        # Check if the object is date (from imports)
        if isinstance(node.func.value, ast.Name):
            return node.func.value.id in self._date_imports
        # Handle datetime.date.today()
        return (
            isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "datetime"
            and node.func.value.attr == "date"
        )

    def _is_time_time_call(self, node: ast.Call) -> bool:
        """Check if call is time.time()."""
        # Direct call: time() after `from time import time` or `from time import time as now_s`
        if isinstance(node.func, ast.Name):
            # Check if the function name is in time imports (handles aliases)
            return node.func.id in self._time_imports

        # Attribute call: time.time()
        if isinstance(node.func, ast.Attribute):
            if node.func.attr != "time":
                return False
            if isinstance(node.func.value, ast.Name):
                # time.time() where time module is imported
                return node.func.value.id == "time" and "time" in self._time_imports

        return False

    def _has_real_time_marker(
        self, func: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> bool:
        """Check if function has @real_time marker with required reason parameter.

        Only accepts markers that are called with a reason argument (non-empty string).
        Rejects @pytest.mark.real_time without arguments to enforce explicit rationale.
        """
        for decorator in func.decorator_list:
            # Only accept Call nodes (markers with arguments)
            if not isinstance(decorator, ast.Call):
                continue

            func_node = decorator.func

            # Check for @real_time(...) - direct import from markers module
            if (
                isinstance(func_node, ast.Name)
                and func_node.id == "real_time"
                or isinstance(func_node, ast.Attribute)
                and (
                    func_node.attr == "real_time"
                    and isinstance(func_node.value, ast.Attribute)
                    and func_node.value.attr == "mark"
                    and isinstance(func_node.value.value, ast.Name)
                    and func_node.value.value.id == "pytest"
                )
            ) and self._has_valid_reason_argument(decorator):
                return True

        return False

    def _has_valid_reason_argument(self, call_node: ast.Call) -> bool:
        """Check if call node has a non-empty reason keyword argument."""
        for keyword in call_node.keywords:
            if keyword.arg == "reason":
                # Check if reason is a non-empty string literal
                if isinstance(keyword.value, ast.Constant):
                    reason_value = keyword.value.value
                    if isinstance(reason_value, str) and reason_value.strip():
                        return True
                # Also handle older Python versions with ast.Str
                elif isinstance(keyword.value, ast.Str):  # type: ignore[attr-defined]
                    reason_value = keyword.value.s  # type: ignore[attr-defined]
                    if isinstance(reason_value, str) and reason_value.strip():
                        return True
        return False

    def _is_exempted(self, func: ast.FunctionDef | ast.AsyncFunctionDef | None) -> bool:
        """Check if current violation is exempted.

        Precedence order (most specific to least specific):
        1. Allow-list nodeid entries (exact test match)
        2. Per-test @real_time marker
        3. Allow-list glob patterns (file/directory patterns)
        """
        if func is None:
            return False

        # Build pytest nodeid: tests/unit/test_file.py::test_function
        rel_path = self._file_path.relative_to(self._repo_root).as_posix()
        nodeid = f"{rel_path}::{func.name}"

        # 1. Check allow-list nodeid (highest precedence)
        if is_exempted(nodeid, self._allowlist):
            return True

        # 2. Check marker (second precedence)
        if self._has_real_time_marker(func):
            return True

        # 3. Check allow-list glob patterns (lowest precedence)
        return bool(is_exempted(rel_path, self._allowlist))

    def _add_datetime_violation(self, node: ast.Call) -> None:
        """Add violation for datetime.now() or datetime.utcnow()."""
        if self._is_exempted(self._current_test_function):
            return

        attr_name = (
            node.func.attr if isinstance(node.func, ast.Attribute) else "unknown"
        )
        self.findings.append(
            LintFinding(
                file=str(self._file_path).replace("\\", "/"),
                line=node.lineno,
                column=node.col_offset,
                rule="TIME001",
                message=(
                    f"Unguarded datetime.{attr_name}() call. "
                    "Use freezegun freeze_time context or TimeOverride for deterministic tests. "
                    "If real time is required, add @real_time(reason='...') marker."
                ),
            )
        )

    def _add_date_today_violation(self, node: ast.Call) -> None:
        """Add violation for date.today()."""
        if self._is_exempted(self._current_test_function):
            return

        self.findings.append(
            LintFinding(
                file=str(self._file_path).replace("\\", "/"),
                line=node.lineno,
                column=node.col_offset,
                rule="TIME002",
                message=(
                    "Unguarded date.today() call. "
                    "Use freezegun freeze_time context or TimeOverride for deterministic tests. "
                    "If real time is required, add @real_time(reason='...') marker."
                ),
            )
        )

    def _add_time_violation(self, node: ast.Call) -> None:
        """Add violation for time.time()."""
        if self._is_exempted(self._current_test_function):
            return

        self.findings.append(
            LintFinding(
                file=str(self._file_path).replace("\\", "/"),
                line=node.lineno,
                column=node.col_offset,
                rule="TIME003",
                message=(
                    "Unguarded time.time() call. "
                    "Use FakeClockContext or TimeOverride for deterministic tests. "
                    "If real time is required, add @real_time(reason='...') marker."
                ),
            )
        )


def _scan_repo_for_time_usage(
    repo_root: Path, allowlist: dict[str, Any]
) -> list[LintFinding]:
    """Scan repository for unguarded real-time reads."""
    findings: list[LintFinding] = []

    for file_path in _iter_time_usage_lint_files(repo_root):
        # Skip if file is exempted by glob pattern
        rel_path = file_path.relative_to(repo_root).as_posix()
        if is_exempted(rel_path, allowlist):
            continue

        try:
            source = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = file_path.read_text(encoding="latin-1")
        except OSError:
            continue

        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError:
            continue

        scanner = _TimeUsageScanner(
            file_path=file_path, repo_root=repo_root, allowlist=allowlist
        )
        scanner.visit(tree)
        findings.extend(scanner.findings)

    return findings


def _get_findings_with_cache(repo_root: Path, cache_path: Path) -> list[LintFinding]:
    """Get findings with two-stage caching support.

    Stage 1: Fast hash check (paths + sizes only) - very fast, avoids mtime checks
    Stage 2: Full fingerprint check (paths + sizes + mtimes) - only if fast hash changed
    Stage 3: Full AST scan - only if fingerprint changed
    """
    # Stage 1: Compute fast hash (paths + sizes only)
    fast_hash, file_count = _compute_fast_hash(repo_root)
    cached = _load_time_usage_lint_cache(cache_path)

    # If cache exists and fast hash matches, return cached results immediately
    # This avoids expensive mtime checks and full scan when nothing changed
    if cached and cached.get("fast_hash") == fast_hash:
        cached_findings = cached.get("findings")
        if isinstance(cached_findings, list):
            return [
                LintFinding(
                    file=str(entry.get("file", "")),
                    line=int(entry.get("line", 1)),
                    column=int(entry.get("column", 0)),
                    rule=str(entry.get("rule", "")),
                    message=str(entry.get("message", "")),
                )
                for entry in cached_findings
                if isinstance(entry, dict)
            ]
        return []

    # Stage 2: Fast hash changed, compute full fingerprint (includes mtimes)
    fingerprint, _ = _compute_time_usage_lint_fingerprint(repo_root)

    # If full fingerprint matches cache, return cached results
    # (file was touched but content didn't change)
    if cached and cached.get("fingerprint") == fingerprint:
        cached_findings = cached.get("findings")
        if isinstance(cached_findings, list):
            # Update cache with new fast_hash (file was touched)
            _atomic_write_json(
                cache_path,
                {
                    "version": _TIME_USAGE_LINT_CACHE_VERSION,
                    "fast_hash": fast_hash,
                    "fingerprint": fingerprint,
                    "file_count": file_count,
                    "findings": cached_findings,
                },
            )
            return [
                LintFinding(
                    file=str(entry.get("file", "")),
                    line=int(entry.get("line", 1)),
                    column=int(entry.get("column", 0)),
                    rule=str(entry.get("rule", "")),
                    message=str(entry.get("message", "")),
                )
                for entry in cached_findings
                if isinstance(entry, dict)
            ]
        return []

    # Stage 3: Fingerprint changed, run full AST scan
    allowlist = load_allowlist()
    findings = _scan_repo_for_time_usage(repo_root, allowlist)
    _atomic_write_json(
        cache_path,
        {
            "version": _TIME_USAGE_LINT_CACHE_VERSION,
            "fast_hash": fast_hash,
            "fingerprint": fingerprint,
            "file_count": file_count,
            "findings": [
                {
                    "file": finding.file,
                    "line": finding.line,
                    "column": finding.column,
                    "rule": finding.rule,
                    "message": finding.message,
                }
                for finding in findings
            ],
        },
    )
    return findings


def test_time_usage_linter() -> None:
    """Test that no unguarded real-time reads exist in tests."""
    repo_root = Path(__file__).resolve().parents[2]
    cache_path = repo_root / ".pytest_cache" / "time_usage_lint_cache.json"
    findings = _get_findings_with_cache(repo_root, cache_path)

    assert not findings, "\n".join(
        f"{f.file}:{f.line}:{f.column} {f.rule} {f.message}" for f in findings
    )


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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    assert len(scanner.findings) == 1
    assert scanner.findings[0].rule == "TIME003"


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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    assert len(scanner.findings) == 0


def test_cache_fast_hash_skips_full_scan(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
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
            "version": _TIME_USAGE_LINT_CACHE_VERSION,
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
        sys.modules[__name__], "_compute_time_usage_lint_fingerprint", _boom_fingerprint
    )
    monkeypatch.setattr(sys.modules[__name__], "_scan_repo_for_time_usage", _boom_scan)

    # This should return cached results without calling fingerprint or scan
    findings = _get_findings_with_cache(repo_root, cache_path)

    assert findings == []
    assert (
        not fingerprint_called
    ), "Fast hash cache hit should skip fingerprint computation"
    assert not scan_called, "Fast hash cache hit should skip full scan"


def test_cache_fingerprint_skips_scan_when_content_unchanged(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
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
            "version": _TIME_USAGE_LINT_CACHE_VERSION,
            "fast_hash": fast_hash_1,
            "fingerprint": fingerprint_1,
            "file_count": file_count,
            "findings": [],
        },
    )

    # Touch the file (change mtime but not content)
    import time

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

    monkeypatch.setattr(sys.modules[__name__], "_scan_repo_for_time_usage", _boom_scan)

    # This should return cached results without calling scan
    # (fast hash changed triggers fingerprint check, fingerprint matches)
    findings = _get_findings_with_cache(repo_root, cache_path)

    assert findings == []
    assert not scan_called, "Fingerprint cache hit should skip full scan"


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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    # Should detect unguarded datetime.now() even though time.time() is guarded
    assert len(scanner.findings) == 1
    assert scanner.findings[0].rule == "TIME001"
    assert "datetime.now()" in scanner.findings[0].message


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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    # test_example should be exempted by nodeid
    # test_other should be exempted by glob
    # So no findings
    assert len(scanner.findings) == 0


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
    scanner = _TimeUsageScanner(
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
    scanner = _TimeUsageScanner(
        file_path=file_path, repo_root=repo_root, allowlist=allowlist
    )
    tree = ast.parse(sample, filename=str(file_path))
    scanner.visit(tree)

    assert len(scanner.findings) == 1
    assert scanner.findings[0].rule == "TIME002"
    assert "date.today()" in scanner.findings[0].message
