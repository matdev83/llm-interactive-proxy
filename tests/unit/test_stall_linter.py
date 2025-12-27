from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LintFinding:
    file: str
    line: int
    rule: str
    message: str


_STALL_LINT_CACHE_VERSION = 2

_STALL_LINT_IGNORE_RE = re.compile(
    r"stall-lint:\s*ignore\s*=\s*([A-Za-z0-9_,*\s-]+)", re.IGNORECASE
)


def _parse_stall_lint_ignored_rules(raw: str) -> set[str]:
    tokens = [t.strip().upper() for t in re.split(r"[,\s]+", raw.strip()) if t.strip()]
    return set(tokens)


def _build_stall_lint_suppressions(source: str) -> dict[int, set[str]]:
    """
    Parse per-line suppressions for the stall-linter.

    Supported forms:
      - Inline: `some_code()  # stall-lint: ignore=STALL002`
      - Next-line: `# stall-lint: ignore=STALL002` applies to the next
        non-empty, non-comment line.
    """

    suppressions: dict[int, set[str]] = {}
    pending: set[str] | None = None

    for line_no, line in enumerate(source.splitlines(), start=1):
        match = _STALL_LINT_IGNORE_RE.search(line)
        if match:
            ignored = _parse_stall_lint_ignored_rules(match.group(1))
            if line.lstrip().startswith("#"):
                pending = ignored
                continue
            suppressions.setdefault(line_no, set()).update(ignored)
            continue

        if pending is not None:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            suppressions.setdefault(line_no, set()).update(pending)
            pending = None

    return suppressions


def _is_suppressed(finding: LintFinding, suppressions: dict[int, set[str]]) -> bool:
    ignored = suppressions.get(finding.line)
    if not ignored:
        return False
    if "*" in ignored or "ALL" in ignored:
        return True
    return finding.rule in ignored


def _iter_stall_lint_files(repo_root: Path) -> list[Path]:
    roots = [
        repo_root / "tests",
        repo_root / "src" / "connectors",
    ]

    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        files.extend(root.rglob("*.py"))
    return sorted(files)


def _compute_stall_lint_fingerprint(repo_root: Path) -> tuple[str, int]:
    """
    Compute a cheap fingerprint of the linted Python tree.

    Uses relative path + file size + mtime_ns (no file reads), so a stable tree
    skips full AST scans on repeated runs.
    """

    hasher = hashlib.blake2b(digest_size=16)
    count = 0
    for file_path in _iter_stall_lint_files(repo_root):
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


def _load_stall_lint_cache(cache_path: Path) -> dict[str, Any] | None:
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
    if data.get("version") != _STALL_LINT_CACHE_VERSION:
        return None
    return data


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _scan_repo_for_stalls(repo_root: Path) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for file_path in _iter_stall_lint_files(repo_root):
        try:
            source = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = file_path.read_text(encoding="latin-1")

        suppressions = _build_stall_lint_suppressions(source)
        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError:
            continue

        patch_visitor = _PatchRecursionVisitor(file_path=file_path)
        patch_visitor.visit(tree)
        file_findings = list(patch_visitor.findings)

        if any(
            token in source for token in ("watchdog", "Observer", "observer", "Watcher")
        ):
            watchdog_visitor = _WatchdogShutdownVisitor(file_path=file_path)
            watchdog_visitor.visit(tree)
            file_findings.extend(watchdog_visitor.findings)

        findings.extend(
            finding
            for finding in file_findings
            if not _is_suppressed(finding, suppressions)
        )
    return findings


def _get_findings_with_cache(repo_root: Path, cache_path: Path) -> list[LintFinding]:
    fingerprint, file_count = _compute_stall_lint_fingerprint(repo_root)
    cached = _load_stall_lint_cache(cache_path)
    if cached and cached.get("fingerprint") == fingerprint:
        cached_findings = cached.get("findings")
        if isinstance(cached_findings, list):
            return [
                LintFinding(
                    file=str(entry.get("file", "")),
                    line=int(entry.get("line", 1)),
                    rule=str(entry.get("rule", "")),
                    message=str(entry.get("message", "")),
                )
                for entry in cached_findings
                if isinstance(entry, dict)
            ]
        return []

    findings = _scan_repo_for_stalls(repo_root)
    _atomic_write_json(
        cache_path,
        {
            "version": _STALL_LINT_CACHE_VERSION,
            "fingerprint": fingerprint,
            "file_count": file_count,
            "findings": [
                {
                    "file": finding.file,
                    "line": finding.line,
                    "rule": finding.rule,
                    "message": finding.message,
                }
                for finding in findings
            ],
        },
    )
    return findings


class _PatchRecursionVisitor(ast.NodeVisitor):
    def __init__(self, *, file_path: Path) -> None:
        self._file_path = file_path
        self.findings: list[LintFinding] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        target = self._patched_target(node)
        if target in {"asyncio.sleep", "time.time"}:
            self._check_patch_args(node, target)
        self.generic_visit(node)

    def _patched_target(self, node: ast.Call) -> str | None:
        func = node.func
        if (
            isinstance(func, ast.Name)
            and func.id == "patch"
            or isinstance(func, ast.Attribute)
            and func.attr == "patch"
        ):
            pass
        else:
            return None

        if not node.args:
            return None
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
        return None

    def _check_patch_args(self, node: ast.Call, target: str) -> None:
        for kw in node.keywords:
            if kw.arg == "return_value" and self._references_patched_symbol(
                kw.value, target
            ):
                self._add(
                    node,
                    rule="STALL001",
                    message=(
                        f"Recursive patch: patch({target!r}, return_value=...) "
                        f"references {target!r}. Capture the original first, e.g. "
                        f"`original = asyncio.sleep` then use `original(0)`."
                    ),
                )
            if (
                kw.arg == "side_effect"
                and isinstance(kw.value, ast.Lambda)
                and self._references_patched_symbol(kw.value.body, target)
            ):
                self._add(
                    node,
                    rule="STALL002",
                    message=(
                        f"Recursive patch: patch({target!r}, side_effect=lambda ...: ...) "
                        f"references {target!r}. Capture the original first and call that."
                    ),
                )

    def _references_patched_symbol(self, node: ast.AST, target: str) -> bool:
        module_name, attr = target.split(".", 1)

        class _RefFinder(ast.NodeVisitor):
            def __init__(self) -> None:
                self.found = False

            def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
                if (
                    isinstance(node.value, ast.Name)
                    and node.value.id == module_name
                    and node.attr == attr
                ):
                    self.found = True
                    return
                self.generic_visit(node)

        finder = _RefFinder()
        finder.visit(node)
        return finder.found

    def _add(self, node: ast.AST, *, rule: str, message: str) -> None:
        line = getattr(node, "lineno", 1)
        self.findings.append(
            LintFinding(
                file=str(self._file_path).replace("\\", "/"),
                line=int(line),
                rule=rule,
                message=message,
            )
        )


class _WatchdogShutdownVisitor(ast.NodeVisitor):
    def __init__(self, *, file_path: Path) -> None:
        self._file_path = file_path
        self.findings: list[LintFinding] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        methods: dict[str, ast.AST] = {}
        for item in node.body:
            if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                methods[item.name] = item

        stop_method = methods.get("stop")
        schedule_method = methods.get("schedule_reload")
        shutdown_method = methods.get("shutdown")
        cancel_method = methods.get("cancel_pending_reload")

        if stop_method is not None:
            self._check_short_join_without_verification(stop_method, node.name)

        if shutdown_method is not None:
            self._check_shutdown_order(shutdown_method, node.name)

        if (
            node.name == "CredentialWatcher"
            and stop_method is not None
            and schedule_method is not None
        ):
            self._check_shutdown_guard(schedule_method, stop_method)

        if node.name == "CredentialWatcher" and cancel_method is not None:
            self._check_thread_lock_await(cancel_method)

        self.generic_visit(node)

    def _check_short_join_without_verification(
        self, method: ast.AST, class_name: str
    ) -> None:
        join_timeouts: list[tuple[ast.Call, float]] = []
        has_is_alive_check = False

        for node in ast.walk(method):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            if node.func.attr in {"is_alive", "isAlive"}:
                has_is_alive_check = True
            if node.func.attr != "join":
                continue
            timeout = self._extract_join_timeout_seconds(node)
            if timeout is not None:
                join_timeouts.append((node, timeout))

        for call, timeout in join_timeouts:
            if timeout < 2.0 and not has_is_alive_check:
                self._add(
                    call,
                    rule="STALL010",
                    message=(
                        f"{class_name}.stop() uses join(timeout={timeout}) without verifying "
                        "termination (e.g. is_alive()). This can leave zombie Observer threads "
                        "and wedge/kill xdist workers."
                    ),
                )

    def _extract_join_timeout_seconds(self, call: ast.Call) -> float | None:
        for kw in call.keywords:
            if kw.arg == "timeout" and isinstance(kw.value, ast.Constant):
                value = kw.value.value
                if isinstance(value, int | float):
                    return float(value)
        if call.args and isinstance(call.args[0], ast.Constant):
            value = call.args[0].value
            if isinstance(value, int | float):
                return float(value)
        return None

    def _check_shutdown_order(self, method: ast.AST, class_name: str) -> None:
        stop_index: int | None = None
        cancel_index: int | None = None

        body = getattr(method, "body", [])
        if not isinstance(body, list):
            return

        for idx, stmt in enumerate(body):
            call = self._unwrap_stmt_call(stmt)
            if call is None:
                continue
            dotted = self._call_dotted_name(call)
            if dotted is None:
                continue

            if dotted.endswith(".stop") and stop_index is None:
                stop_index = idx
            if dotted.endswith(".cancel_pending_reload") and cancel_index is None:
                cancel_index = idx

        if (
            stop_index is not None
            and cancel_index is not None
            and stop_index < cancel_index
        ):
            self._add(
                method,
                rule="STALL011",
                message=(
                    f"{class_name}.shutdown() stops the observer before cancelling pending reloads. "
                    "Reverse the order to avoid deadlocks and worker hangs."
                ),
            )

    def _check_shutdown_guard(
        self, schedule_method: ast.AST, stop_method: ast.AST
    ) -> None:
        stop_sets_flag = self._method_assigns_attr(stop_method, "_shutdown_requested")
        schedule_checks_flag = self._method_references_attr(
            schedule_method, "_shutdown_requested"
        )
        if stop_sets_flag and schedule_checks_flag:
            return

        self._add(
            schedule_method,
            rule="STALL012",
            message=(
                "CredentialWatcher should prevent new reload scheduling during shutdown "
                "(e.g. `_shutdown_requested` set in stop() and checked in schedule_reload()). "
                "Without this, watchdog callbacks can race with teardown and crash/stall xdist."
            ),
        )

    def _check_thread_lock_await(self, method: ast.AST) -> None:
        """
        Detect deadlocks from holding threading.Lock across an `await`.

        Common failure mode:
          - `with self._reload_task_lock: ... await task`
          - task done-callback also takes the lock -> deadlock at teardown.
        """

        for node in ast.walk(method):
            if not isinstance(node, ast.With):
                continue

            for item in node.items:
                ctx = item.context_expr
                if not self._is_self_attr(
                    ctx, "_reload_task_lock"
                ) and not self._is_self_attr(ctx, "reload_task_lock"):
                    continue

                if any(isinstance(child, ast.Await) for child in ast.walk(node)):
                    self._add(
                        node,
                        rule="STALL013",
                        message=(
                            "Async method holds a threading.Lock across an `await` (e.g. "
                            "`with self._reload_task_lock: await ...`). This can deadlock "
                            "xdist workers during teardown."
                        ),
                    )
                    return

    def _method_assigns_attr(self, method: ast.AST, attr_name: str) -> bool:
        for node in ast.walk(method):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if self._is_self_attr(target, attr_name):
                        return True
            if isinstance(node, ast.AnnAssign) and self._is_self_attr(
                node.target, attr_name
            ):
                return True
        return False

    def _method_references_attr(self, method: ast.AST, attr_name: str) -> bool:
        for node in ast.walk(method):
            if isinstance(node, ast.Attribute) and self._is_self_attr(node, attr_name):
                return True
        return False

    def _is_self_attr(self, node: ast.AST, attr_name: str) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == attr_name
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        )

    def _unwrap_stmt_call(self, stmt: ast.stmt) -> ast.Call | None:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            return stmt.value
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Await):
            value = stmt.value.value
            if isinstance(value, ast.Call):
                return value
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
            return stmt.value
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.value, ast.Call):
            return stmt.value
        return None

    def _call_dotted_name(self, call: ast.Call) -> str | None:
        func = call.func
        parts: list[str] = []
        while isinstance(func, ast.Attribute):
            parts.append(func.attr)
            func = func.value
        if isinstance(func, ast.Name):
            parts.append(func.id)
            return ".".join(reversed(parts))
        return None

    def _add(self, node: ast.AST, *, rule: str, message: str) -> None:
        line = getattr(node, "lineno", 1)
        self.findings.append(
            LintFinding(
                file=str(self._file_path).replace("\\", "/"),
                line=int(line),
                rule=rule,
                message=message,
            )
        )


def test_stall_linter_recursion_patches() -> None:
    """
    Prevent test-suite stalls caused by recursive monkeypatching of time/sleep.

    We've had real hangs from patterns like:
      - patch("asyncio.sleep", return_value=asyncio.sleep(0))
      - patch("asyncio.sleep", side_effect=lambda ...: asyncio.sleep(0))
    """
    repo_root = Path(__file__).resolve().parents[2]
    cache_path = repo_root / ".pytest_cache" / "stall_lint_cache.json"
    findings = _get_findings_with_cache(repo_root, cache_path)

    assert not findings, "\n".join(
        f"{f.file}:{f.line} {f.rule} {f.message}" for f in findings
    )


def test_stall_linter_suppression_mechanism(tmp_path: Path) -> None:
    sample = """\
import asyncio
from unittest.mock import patch


def test_example():
    # stall-lint: ignore=STALL002
    patch("asyncio.sleep", side_effect=lambda *_a, **_kw: asyncio.sleep(0))
"""
    file_path = tmp_path / "sample_test.py"
    file_path.write_text(sample, encoding="utf-8")

    suppressions = _build_stall_lint_suppressions(sample)
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _PatchRecursionVisitor(file_path=file_path)
    visitor.visit(tree)

    unsuppressed = visitor.findings
    assert [f.rule for f in unsuppressed] == ["STALL002"]

    suppressed = [
        finding
        for finding in visitor.findings
        if not _is_suppressed(finding, suppressions)
    ]
    assert suppressed == []


def test_stall_linter_detects_forbidden_recursive_patch(tmp_path: Path) -> None:
    sample = """\
import asyncio
from unittest.mock import patch


def test_example():
    patch("asyncio.sleep", return_value=asyncio.sleep(0))
"""
    file_path = tmp_path / "sample_test.py"
    file_path.write_text(sample, encoding="utf-8")

    suppressions = _build_stall_lint_suppressions(sample)
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _PatchRecursionVisitor(file_path=file_path)
    visitor.visit(tree)

    assert [f.rule for f in visitor.findings] == ["STALL001"]
    assert not _is_suppressed(visitor.findings[0], suppressions)


def test_stall_linter_detects_short_join_without_is_alive(tmp_path: Path) -> None:
    sample = """\
from watchdog.observers import Observer


class SomethingWatcher:
    def __init__(self):
        self._observer = Observer()

    def stop(self):
        self._observer.stop()
        self._observer.join(timeout=1.0)
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _WatchdogShutdownVisitor(file_path=file_path)
    visitor.visit(tree)
    assert "STALL010" in {finding.rule for finding in visitor.findings}


def test_stall_linter_detects_shutdown_order_issue(tmp_path: Path) -> None:
    sample = """\
class Manager:
    def __init__(self):
        self._watcher = None

    async def shutdown(self):
        self._watcher.stop()
        await self._watcher.cancel_pending_reload()
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _WatchdogShutdownVisitor(file_path=file_path)
    visitor.visit(tree)
    assert "STALL011" in {finding.rule for finding in visitor.findings}


def test_stall_linter_detects_missing_shutdown_guard(tmp_path: Path) -> None:
    sample = """\
from watchdog.observers import Observer


class CredentialWatcher:
    def __init__(self):
        self._observer = Observer()

    def stop(self):
        self._observer.stop()
        self._observer.join(timeout=5.0)
        if self._observer.is_alive():
            pass

    def schedule_reload(self):
        return
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _WatchdogShutdownVisitor(file_path=file_path)
    visitor.visit(tree)
    assert "STALL012" in {finding.rule for finding in visitor.findings}


def test_stall_linter_detects_lock_await_deadlock_pattern(tmp_path: Path) -> None:
    sample = """\
import asyncio
import threading


class CredentialWatcher:
    def __init__(self):
        self._reload_task_lock = threading.Lock()
        self._pending_reload_task: asyncio.Future | None = None

    async def cancel_pending_reload(self):
        with self._reload_task_lock:
            if self._pending_reload_task is not None:
                await self._pending_reload_task
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _WatchdogShutdownVisitor(file_path=file_path)
    visitor.visit(tree)
    assert "STALL013" in {finding.rule for finding in visitor.findings}


def test_stall_linter_cache_hit_skips_scan(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
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

    def _boom(_path: Path) -> list[LintFinding]:
        raise AssertionError("Expected cache hit; scan should not run")

    monkeypatch.setattr(sys.modules[__name__], "_scan_repo_for_stalls", _boom)
    assert _get_findings_with_cache(repo_root, cache_path) == []
