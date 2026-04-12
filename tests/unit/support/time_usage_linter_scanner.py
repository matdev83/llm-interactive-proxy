"""AST scanner and cached repository scan for the time usage linter.

Used by unit tests and dev scripts to detect unguarded real-time reads under
``tests/`` with optional two-stage fingerprint caching.
"""

from __future__ import annotations

import ast
import hashlib
import json
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


TIME_USAGE_LINT_CACHE_VERSION = 1


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
    if data.get("version") != TIME_USAGE_LINT_CACHE_VERSION:
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
    TIME_OVERRIDE = "time_override"


class TimeUsageScanner(ast.NodeVisitor):
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

        # Track current class for marker checking
        self._current_class: ast.ClassDef | None = None

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

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        """Track class-level freeze_time decorators."""
        old_class = self._current_class
        self._current_class = node

        # Check for @freeze_time decorator
        has_freeze = self._has_freezegun_decorator(node)
        if has_freeze:
            self._guard_stack.append(GuardType.FREEZEGUN)

        self.generic_visit(node)

        if has_freeze:
            self._guard_stack.pop()

        self._current_class = old_class

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
        """Track async time guard context managers."""
        # Check if this is a FakeClockContext or TimeOverride
        guard_type = self._detect_async_time_guard(node)
        if guard_type:
            self._guard_stack.append(guard_type)
        self.generic_visit(node)
        if guard_type:
            self._guard_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        """Detect real-time read calls."""
        # Check for datetime.now(), datetime.utcnow()
        if self._is_datetime_now_call(node):
            if not (
                self._is_guarded(GuardType.FREEZEGUN)
                or self._is_guarded(GuardType.TIME_OVERRIDE)
            ):
                self._add_datetime_violation(node)
        # Check for date.today()
        elif self._is_date_today_call(node):
            if not (
                self._is_guarded(GuardType.FREEZEGUN)
                or self._is_guarded(GuardType.TIME_OVERRIDE)
            ):
                self._add_date_today_violation(node)
        # Check for time.time()
        elif self._is_time_time_call(node) and not (
            self._is_guarded(GuardType.FAKE_CLOCK)
            or self._is_guarded(GuardType.TIME_OVERRIDE)
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

    def _detect_async_time_guard(self, node: ast.AsyncWith) -> GuardType | None:
        """Detect if an AsyncWith node is a time guard (FakeClockContext or TimeOverride)."""
        for item in node.items:
            ctx = item.context_expr
            # Check for FakeClockContext(...) or TimeOverride(...) call
            if isinstance(ctx, ast.Call):
                func = ctx.func
                name = ""
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr

                if name == "FakeClockContext":
                    return GuardType.FAKE_CLOCK
                if name == "TimeOverride":
                    return GuardType.TIME_OVERRIDE
        return None

    def _has_freezegun_decorator(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    ) -> bool:
        """Check if node has @freeze_time decorator."""

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
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    ) -> bool:
        """Check if node has @real_time marker with required reason parameter.


        Only accepts markers that are called with a reason argument (non-empty string).
        Rejects @pytest.mark.real_time without arguments to enforce explicit rationale.
        """
        for decorator in node.decorator_list:
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
        # Check function marker
        if self._has_real_time_marker(func):
            return True
        # Check class marker
        if self._current_class and self._has_real_time_marker(self._current_class):
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


def scan_repo_for_time_usage(
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

        scanner = TimeUsageScanner(
            file_path=file_path, repo_root=repo_root, allowlist=allowlist
        )
        scanner.visit(tree)
        findings.extend(scanner.findings)

    return findings


def get_findings_with_cache(repo_root: Path, cache_path: Path) -> list[LintFinding]:
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
                    "version": TIME_USAGE_LINT_CACHE_VERSION,
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
    findings = scan_repo_for_time_usage(repo_root, allowlist)
    _atomic_write_json(
        cache_path,
        {
            "version": TIME_USAGE_LINT_CACHE_VERSION,
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
