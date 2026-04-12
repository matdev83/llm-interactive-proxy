from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

APPROVED_ROUTED_CALL_CHAINS = {
    "self._backend_service.call_completion",
    "backend_service.call_completion",
    "completion_service.call_completion",
    "backend_service.chat_completions",
    "self._backend_service.chat_completions",
}

# Internal delegates that route into shared entry points and should not be treated
# as outbound call-surface bypasses.
APPROVED_INTERNAL_DELEGATE_CALL_CHAINS = {
    "self.call_completion",
    "self._backend_completion_flow.call_completion",
    "self._completion_flow.call_completion",
}

OUTBOUND_CALL_METHOD_SUFFIXES = (
    ".chat_completions",
    ".call_completion",
)


@dataclass(frozen=True)
class DiscoveredCallSite:
    file: str
    function: str
    call: str

    @property
    def key(self) -> str:
        return f"{self.file}::{self.function}::{self.call}"


@dataclass
class ComplianceReport:
    errors: list[str] = field(default_factory=list)
    discovered_keys: set[str] = field(default_factory=set)
    inventory_direct_keys: set[str] = field(default_factory=set)
    bypass_keys: set[str] = field(default_factory=set)


class _CallSiteVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self._function_stack: list[str] = []
        self.call_sites: list[tuple[str, str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._function_stack.append(node.name)
        self.generic_visit(node)
        self._function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._function_stack.append(node.name)
        self.generic_visit(node)
        self._function_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        call_chain = _format_call_chain(node.func)
        if call_chain is not None:
            function_name = (
                self._function_stack[-1] if self._function_stack else "<module>"
            )
            self.call_sites.append((function_name, call_chain))
        self.generic_visit(node)


def _format_call_chain(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _format_call_chain(node.value)
        if prefix is None:
            return None
        return f"{prefix}.{node.attr}"
    return None


def _normalize_relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_outbound_inference_call_chain(call_chain: str) -> bool:
    return call_chain.endswith(OUTBOUND_CALL_METHOD_SUFFIXES)


def _is_in_allowed_boundary(rel_path: str, boundaries: set[str]) -> bool:
    normalized = rel_path.replace("\\", "/")
    for boundary in boundaries:
        normalized_boundary = boundary.replace("\\", "/")
        if normalized_boundary.endswith("/"):
            if normalized.startswith(normalized_boundary):
                return True
            continue
        if normalized == normalized_boundary:
            return True
        if normalized.startswith(f"{normalized_boundary}/"):
            return True
    return False


def load_inventory(inventory_path: Path) -> dict[str, Any]:
    raw_data = yaml.safe_load(inventory_path.read_text(encoding="utf-8"))
    if not isinstance(raw_data, dict):
        raise ValueError("Inventory must be a mapping at root level.")
    call_surfaces = raw_data.get("call_surfaces")
    if not isinstance(call_surfaces, list):
        raise ValueError("Inventory field 'call_surfaces' must be a list.")
    boundaries = raw_data.get("allowed_adapter_boundaries", [])
    if not isinstance(boundaries, list):
        raise ValueError("Inventory field 'allowed_adapter_boundaries' must be a list.")
    scan_roots = raw_data.get("scan_roots", [])
    if scan_roots and not isinstance(scan_roots, list):
        raise ValueError("Inventory field 'scan_roots' must be a list when provided.")
    return raw_data


def _discover_call_sites(
    repo_root: Path,
    *,
    allowed_boundaries: set[str],
    scan_roots: tuple[str, ...],
) -> tuple[set[DiscoveredCallSite], set[str], list[str]]:
    discovered_sites: set[DiscoveredCallSite] = set()
    bypass_sites: set[str] = set()
    parse_errors: list[str] = []

    discovered_files: set[Path] = set()
    for raw_root in scan_roots:
        root = (repo_root / raw_root).resolve()
        if root.is_file():
            discovered_files.add(root)
            continue
        if not root.exists():
            parse_errors.append(f"Scan root does not exist: '{raw_root}'")
            continue
        for py_file in root.rglob("*.py"):
            discovered_files.add(py_file.resolve())

    for py_file in sorted(discovered_files):
        if py_file.name.startswith("test_") or py_file.name.endswith("_test.py"):
            continue
        rel_path = _normalize_relative_path(py_file, repo_root)
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            parse_errors.append(f"Failed to parse '{rel_path}': {exc}")
            continue

        visitor = _CallSiteVisitor()
        visitor.visit(tree)

        for function_name, call_chain in visitor.call_sites:
            if call_chain in APPROVED_ROUTED_CALL_CHAINS:
                discovered_sites.add(
                    DiscoveredCallSite(
                        file=rel_path,
                        function=function_name,
                        call=call_chain,
                    )
                )
            if (
                _is_outbound_inference_call_chain(call_chain)
                and call_chain not in APPROVED_ROUTED_CALL_CHAINS
                and call_chain not in APPROVED_INTERNAL_DELEGATE_CALL_CHAINS
                and not _is_in_allowed_boundary(rel_path, allowed_boundaries)
            ):
                bypass_sites.add(f"{rel_path}::{function_name}::{call_chain}")

    return discovered_sites, bypass_sites, parse_errors


def run_compliance_checks(repo_root: Path, inventory_path: Path) -> ComplianceReport:
    report = ComplianceReport()
    try:
        inventory = load_inventory(inventory_path)
    except Exception as exc:
        report.errors.append(f"Failed to load inventory '{inventory_path}': {exc}")
        return report

    call_surfaces = inventory["call_surfaces"]
    allowed_boundaries = {
        str(boundary) for boundary in inventory.get("allowed_adapter_boundaries", [])
    }
    scan_roots = tuple(
        str(root).strip()
        for root in inventory.get("scan_roots", [])
        if str(root).strip()
    ) or ("src/core/services",)

    direct_entries: list[dict[str, Any]] = []
    indirect_entries: list[dict[str, Any]] = []
    for entry in call_surfaces:
        if not isinstance(entry, dict):
            report.errors.append("Each call surface entry must be a mapping.")
            continue
        kind = str(entry.get("kind", "direct")).strip().lower()
        if kind == "direct":
            direct_entries.append(entry)
        elif kind == "indirect":
            indirect_entries.append(entry)
        else:
            report.errors.append(
                f"Call surface '{entry.get('id', '<unknown>')}' has unknown kind '{kind}'."
            )

    inventory_direct_keys: set[str] = set()
    direct_surface_ids: set[str] = set()
    for entry in direct_entries:
        surface_id = str(entry.get("id", "")).strip()
        file_path = str(entry.get("file", "")).strip()
        function_name = str(entry.get("function", "")).strip()
        call_chain = str(entry.get("call", "")).strip()
        if not surface_id or not file_path or not function_name or not call_chain:
            report.errors.append(
                f"Direct call surface is missing required fields: {entry}"
            )
            continue
        direct_surface_ids.add(surface_id)
        inventory_direct_keys.add(f"{file_path}::{function_name}::{call_chain}")
        if call_chain not in APPROVED_ROUTED_CALL_CHAINS:
            report.errors.append(
                f"Direct call surface '{surface_id}' does not use approved shared routing chain '{call_chain}'."
            )

    discovered_sites, bypass_sites, parse_errors = _discover_call_sites(
        repo_root,
        allowed_boundaries=allowed_boundaries,
        scan_roots=scan_roots,
    )
    report.errors.extend(parse_errors)

    discovered_keys = {site.key for site in discovered_sites}
    report.discovered_keys = discovered_keys
    report.inventory_direct_keys = inventory_direct_keys
    report.bypass_keys = bypass_sites

    for missing_key in sorted(discovered_keys - inventory_direct_keys):
        report.errors.append(
            f"Discovered outbound call surface missing from inventory: {missing_key}"
        )
    for stale_key in sorted(inventory_direct_keys - discovered_keys):
        report.errors.append(
            f"Inventory entry does not match discovered outbound call surface: {stale_key}"
        )
    for bypass_key in sorted(bypass_sites):
        report.errors.append(
            f"Bypass detected outside allowed adapter boundaries: {bypass_key}"
        )

    for entry in indirect_entries:
        surface_id = str(entry.get("id", "")).strip()
        file_path = str(entry.get("file", "")).strip()
        marker = str(entry.get("marker", "")).strip()
        routes_via = str(entry.get("routes_via", "")).strip()

        if not surface_id or not file_path or not marker or not routes_via:
            report.errors.append(
                f"Indirect call surface is missing required fields: {entry}"
            )
            continue
        if routes_via not in direct_surface_ids:
            report.errors.append(
                f"Indirect call surface '{surface_id}' routes via unknown direct surface '{routes_via}'."
            )
        target_file = repo_root / file_path
        if not target_file.exists():
            report.errors.append(
                f"Indirect call surface '{surface_id}' references missing file '{file_path}'."
            )
            continue
        file_text = target_file.read_text(encoding="utf-8")
        if marker not in file_text:
            report.errors.append(
                f"Indirect call surface '{surface_id}' marker not found in '{file_path}'."
            )

    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate outbound routing unification compliance."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root path.",
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        default=None,
        help="Path to unified routing inventory YAML.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    inventory_path = (
        args.inventory.resolve()
        if args.inventory is not None
        else (repo_root / "dev" / "routing" / "unified_routing_inventory.yaml")
    )

    report = run_compliance_checks(repo_root=repo_root, inventory_path=inventory_path)
    if report.errors:
        print("routing-unification-compliance: FAILED")
        for error in report.errors:
            print(f"- {error}")
        return 1

    print("routing-unification-compliance: PASSED")
    print(
        "Validated "
        f"{len(report.discovered_keys)} discovered direct call surfaces "
        f"against {len(report.inventory_direct_keys)} inventory entries."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
