"""Time usage linter to prevent unsafe real-time reads in tests.

This linter scans tests for unguarded calls to real system wall-clock time
APIs and fails unless explicitly exempted via @real_time marker or allow-list.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
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


def _compute_time_usage_lint_fingerprint(repo_root: Path) -> tuple[str, int]:
    """Compute fingerprint of linted Python tree for caching."""
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


class GuardType:
    """Types of guard contexts."""

    FREEZEGUN = "freezegun"
    FAKE_CLOCK = "fake_clock"


class _TimeUsageScanner(ast.NodeVisitor):
    """AST visitor to detect unguarded real-time reads in tests."""

    def __init__(self, *, file_path: Path, repo_root: Path, allowlist: dict[str, Any]) -> None:
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
        self._current_test_function: ast.FunctionDef | None = None
        self._test_functions: list[ast.FunctionDef] = []

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
        """Track freeze_time context managers."""
        # Check if this is a freeze_time context
        guard_type = self._detect_freezegun_guard(node)
        if guard_type:
            self._guard_stack.append(guard_type)
        self.generic_visit(node)
        if guard_type:
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
        elif self._is_time_time_call(node):
            if not self._is_guarded(GuardType.FAKE_CLOCK):
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
                elif isinstance(func, ast.Attribute):
                    if func.attr == "freeze_time":
                        return GuardType.FREEZEGUN
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
                elif isinstance(func, ast.Attribute):
                    if func.attr == "FakeClockContext":
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
                elif isinstance(func_node, ast.Attribute):
                    if func_node.attr == "freeze_time":
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
        elif isinstance(node.func.value, ast.Attribute):
            # Handle datetime.datetime.now()
            if (
                isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "datetime"
                and node.func.value.attr == "datetime"
            ):
                return True

        return False

    def _is_date_today_call(self, node: ast.Call) -> bool:
        """Check if call is date.today()."""
        if not isinstance(node.func, ast.Attribute):
            return False

        if node.func.attr != "today":
            return False

        # Check if the object is date (from imports)
        if isinstance(node.func.value, ast.Name):
            return node.func.value.id in self._date_imports
        elif isinstance(node.func.value, ast.Attribute):
            # Handle datetime.date.today()
            if (
                isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "datetime"
                and node.func.value.attr == "date"
            ):
                return True

        return False

    def _is_time_time_call(self, node: ast.Call) -> bool:
        """Check if call is time.time()."""
        # Direct call: time() after `from time import time`
        if isinstance(node.func, ast.Name):
            return node.func.id in self._time_imports and node.func.id == "time"

        # Attribute call: time.time()
        if isinstance(node.func, ast.Attribute):
            if node.func.attr != "time":
                return False
            if isinstance(node.func.value, ast.Name):
                # time.time() where time module is imported
                return node.func.value.id == "time" and "time" in self._time_imports

        return False

    def _has_real_time_marker(self, func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """Check if function has @real_time marker."""
        for decorator in func.decorator_list:
            # Check for @real_time(...) or @pytest.mark.real_time(...)
            if isinstance(decorator, ast.Call):
                func_node = decorator.func
                if isinstance(func_node, ast.Name) and func_node.id == "real_time":
                    return True
                elif isinstance(func_node, ast.Attribute):
                    if (
                        isinstance(func_node.value, ast.Attribute)
                        and func_node.value.attr == "mark"
                        and isinstance(func_node.value.value, ast.Name)
                        and func_node.value.value.id == "pytest"
                        and func_node.attr == "real_time"
                    ):
                        return True
            elif isinstance(decorator, ast.Attribute):
                # @pytest.mark.real_time (without args, but should have reason)
                if (
                    decorator.attr == "real_time"
                    and isinstance(decorator.value, ast.Attribute)
                    and decorator.value.attr == "mark"
                    and isinstance(decorator.value.value, ast.Name)
                    and decorator.value.value.id == "pytest"
                ):
                    return True

        return False

    def _is_exempted(self, func: ast.FunctionDef | ast.AsyncFunctionDef | None) -> bool:
        """Check if current violation is exempted."""
        if func is None:
            return False

        # Build pytest nodeid: tests/unit/test_file.py::test_function
        rel_path = self._file_path.relative_to(self._repo_root).as_posix()
        nodeid = f"{rel_path}::{func.name}"

        # Check allow-list (nodeid and glob patterns)
        if is_exempted(nodeid, self._allowlist):
            return True
        if is_exempted(rel_path, self._allowlist):
            return True

        # Check marker
        if self._has_real_time_marker(func):
            return True

        return False

    def _add_datetime_violation(self, node: ast.Call) -> None:
        """Add violation for datetime.now() or datetime.utcnow()."""
        if self._is_exempted(self._current_test_function):
            return

        attr_name = node.func.attr if isinstance(node.func, ast.Attribute) else "unknown"
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
    """Get findings with caching support."""
    fingerprint, file_count = _compute_time_usage_lint_fingerprint(repo_root)
    cached = _load_time_usage_lint_cache(cache_path)
    if cached and cached.get("fingerprint") == fingerprint:
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

    allowlist = load_allowlist()
    findings = _scan_repo_for_time_usage(repo_root, allowlist)
    _atomic_write_json(
        cache_path,
        {
            "version": _TIME_USAGE_LINT_CACHE_VERSION,
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

