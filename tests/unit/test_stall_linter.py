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


def _compute_tests_fingerprint(test_root: Path) -> tuple[str, int]:
    """
    Compute a cheap fingerprint of the tests tree.

    Uses relative path + file size + mtime_ns (no file reads), so a stable tests
    tree skips full AST scans on repeated runs.
    """

    hasher = hashlib.blake2b(digest_size=16)
    count = 0
    for file_path in sorted(test_root.rglob("*.py")):
        try:
            stat = file_path.stat()
        except OSError:
            continue

        rel = file_path.relative_to(test_root).as_posix()
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
    if data.get("version") != 1:
        return None
    return data


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _scan_tests_for_stalls(test_root: Path) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for file_path in test_root.rglob("*.py"):
        try:
            source = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = file_path.read_text(encoding="latin-1")

        suppressions = _build_stall_lint_suppressions(source)
        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError:
            continue

        visitor = _PatchRecursionVisitor(file_path=file_path)
        visitor.visit(tree)
        findings.extend(
            finding
            for finding in visitor.findings
            if not _is_suppressed(finding, suppressions)
        )
    return findings


def _get_findings_with_cache(test_root: Path, cache_path: Path) -> list[LintFinding]:
    fingerprint, file_count = _compute_tests_fingerprint(test_root)
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

    findings = _scan_tests_for_stalls(test_root)
    _atomic_write_json(
        cache_path,
        {
            "version": 1,
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


def test_stall_linter_recursion_patches() -> None:
    """
    Prevent test-suite stalls caused by recursive monkeypatching of time/sleep.

    We've had real hangs from patterns like:
      - patch("asyncio.sleep", return_value=asyncio.sleep(0))
      - patch("asyncio.sleep", side_effect=lambda ...: asyncio.sleep(0))
    """
    repo_root = Path(__file__).resolve().parents[2]
    test_root = repo_root / "tests"
    cache_path = repo_root / ".pytest_cache" / "stall_lint_cache.json"
    findings = _get_findings_with_cache(test_root, cache_path)

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


def test_stall_linter_cache_hit_skips_scan(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    test_root = tmp_path / "tests"
    test_root.mkdir()
    (test_root / "test_sample.py").write_text("x = 1\n", encoding="utf-8")

    cache_path = tmp_path / ".pytest_cache" / "stall_lint_cache.json"
    fingerprint, file_count = _compute_tests_fingerprint(test_root)
    _atomic_write_json(
        cache_path,
        {
            "version": 1,
            "fingerprint": fingerprint,
            "file_count": file_count,
            "findings": [],
        },
    )

    def _boom(_path: Path) -> list[LintFinding]:
        raise AssertionError("Expected cache hit; scan should not run")

    monkeypatch.setattr(sys.modules[__name__], "_scan_tests_for_stalls", _boom)
    assert _get_findings_with_cache(test_root, cache_path) == []
