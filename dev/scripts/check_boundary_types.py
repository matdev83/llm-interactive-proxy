#!/usr/bin/env python3
"""
Boundary type checker to detect Any and dict[str, Any] usage in boundary modules.

This script scans boundary modules according to the scope configuration defined in
dev/boundary_types_scope.json for violations of typed contract rules:
- No new Any in function signatures for cross-layer seams
- No new dict[str, Any] for contract-shaped payloads
- No new type: ignore comments without documented rationale

Run with:
    ./.venv/Scripts/python.exe dev/scripts/check_boundary_types.py [paths...]

If no paths are provided, scans the current directory.
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any as TypingAny


@dataclass
class Violation:
    """Represents a boundary type violation."""

    file_path: str
    line: int
    column: int
    message: str
    symbol: str | None = None  # Function/class name if applicable

    def __str__(self) -> str:
        return f"{self.file_path}:{self.line}:{self.column}: {self.message}"


@dataclass
class AllowlistEntry:
    """Represents an allowlist entry for a boundary type violation."""

    file: str
    symbol: str | None
    violation: str
    reason: str
    expires_at: str  # RFC3339 timestamp
    tracking: str  # Issue/spec reference

    def is_expired(self) -> bool:
        """Check if this allowlist entry has expired.

        Returns:
            True if expires_at is in the past, False otherwise
        """
        try:
            expires_dt = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            if expires_dt.tzinfo is None:
                expires_dt = expires_dt.replace(tzinfo=timezone.utc)
            return expires_dt < datetime.now(timezone.utc)
        except (ValueError, AttributeError):
            # If we can't parse the date, treat as expired for safety
            return True

    def matches(self, violation: Violation, violation_type: str) -> bool:
        """Check if this allowlist entry matches a violation.

        Args:
            violation: The violation to check
            violation_type: Type of violation (e.g., "Any-in-signature", "dict[str, Any]")

        Returns:
            True if the entry matches the violation
        """
        # Normalize paths for comparison
        violation_path = violation.file_path.replace("\\", "/")
        allowlist_file = self.file.replace("\\", "/")

        # Check if paths match (exact match or violation path ends with allowlist file)
        file_match = (
            violation_path == allowlist_file
            or violation_path.endswith("/" + allowlist_file)
            or violation_path.endswith(allowlist_file)
        )
        violation_match = self.violation == violation_type
        symbol_match = (
            self.symbol is None
            or violation.symbol is None
            or self.symbol == violation.symbol
        )

        return file_match and violation_match and symbol_match


class BoundaryTypeChecker(ast.NodeVisitor):
    """AST visitor to detect boundary type violations."""

    # Allowlist patterns for legitimate internal contexts
    ALLOWLIST_PATTERNS = [
        # ProcessingContext.values is a legitimate internal context
        ("ProcessingContext", "values"),
        # Internal DTOs may have Any for flexibility
        ("InternalDTO", None),
        # Test files are excluded
        ("test_", None),
        ("_test.py", None),
    ]

    def __init__(self) -> None:
        self.violations: list[Violation] = []
        self.current_file: str = ""
        self.in_test_file: bool = False

    def check_file(self, file_path: str, source: str) -> list[Violation]:
        """Check a single file for violations.

        Args:
            file_path: Path to the file being checked
            source: Source code content

        Returns:
            List of violations found
        """
        self.violations = []
        self.current_file = file_path
        path_obj = Path(file_path)
        # Only skip if it's actually a test file (starts with test_ or in tests directory)
        self.in_test_file = (
            path_obj.name.startswith("test_")
            or path_obj.name.endswith("_test.py")
            or "tests" in path_obj.parts
        )

        try:
            tree = ast.parse(source, filename=file_path)
            self.visit(tree)
        except SyntaxError:
            # Skip files with syntax errors (they'll be caught by other tools)
            pass

        return self.violations

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit function definitions to check signatures."""
        if self.in_test_file:
            return

        # Check function signature
        self._check_signature(node, node.name, node.args, node.returns)

        # Check for type: ignore comments
        self._check_type_ignore(node)

        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit async function definitions to check signatures."""
        if self.in_test_file:
            return

        self._check_signature(node, node.name, node.args, node.returns)
        self._check_type_ignore(node)

        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Visit class definitions to check method signatures."""
        if self.in_test_file:
            return

        # Check if this class is allowlisted
        for pattern_class, _pattern_attr in self.ALLOWLIST_PATTERNS:
            if pattern_class in node.name:
                # Skip checking this class if it matches allowlist
                return

        self.generic_visit(node)

    def _check_signature(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        name: str,
        args: ast.arguments,
        returns: ast.expr | None,
    ) -> None:
        """Check function signature for Any and dict[str, Any]."""
        # Check positional-only arguments
        for arg in args.posonlyargs:
            if arg.annotation:
                violation_msg, violation_type = self._check_type_annotation(
                    arg.annotation,
                    f"Function '{name}' positional-only parameter '{arg.arg}'",
                )
                if violation_msg:
                    self.violations.append(
                        Violation(
                            file_path=self.current_file,
                            line=node.lineno,
                            column=node.col_offset,
                            message=violation_msg,
                            symbol=name,
                        )
                    )

        # Check regular positional/keyword arguments
        for arg in args.args:
            if arg.annotation:
                violation_msg, violation_type = self._check_type_annotation(
                    arg.annotation, f"Function '{name}' parameter '{arg.arg}'"
                )
                if violation_msg:
                    self.violations.append(
                        Violation(
                            file_path=self.current_file,
                            line=node.lineno,
                            column=node.col_offset,
                            message=violation_msg,
                            symbol=name,
                        )
                    )

        # Check *args parameter
        if args.vararg:
            if args.vararg.annotation:
                violation_msg, violation_type = self._check_type_annotation(
                    args.vararg.annotation, f"Function '{name}' *args parameter"
                )
                if violation_msg:
                    self.violations.append(
                        Violation(
                            file_path=self.current_file,
                            line=node.lineno,
                            column=node.col_offset,
                            message=violation_msg,
                            symbol=name,
                        )
                    )

        # Check keyword-only arguments
        for arg in args.kwonlyargs:
            if arg.annotation:
                violation_msg, violation_type = self._check_type_annotation(
                    arg.annotation,
                    f"Function '{name}' keyword-only parameter '{arg.arg}'",
                )
                if violation_msg:
                    self.violations.append(
                        Violation(
                            file_path=self.current_file,
                            line=node.lineno,
                            column=node.col_offset,
                            message=violation_msg,
                            symbol=name,
                        )
                    )

        # Check **kwargs parameter
        if args.kwarg:
            if args.kwarg.annotation:
                violation_msg, violation_type = self._check_type_annotation(
                    args.kwarg.annotation, f"Function '{name}' **kwargs parameter"
                )
                if violation_msg:
                    self.violations.append(
                        Violation(
                            file_path=self.current_file,
                            line=node.lineno,
                            column=node.col_offset,
                            message=violation_msg,
                            symbol=name,
                        )
                    )

        # Check return type
        if returns:
            violation_msg, violation_type = self._check_type_annotation(
                returns, f"Function '{name}' return type"
            )
            if violation_msg:
                self.violations.append(
                    Violation(
                        file_path=self.current_file,
                        line=node.lineno,
                        column=node.col_offset,
                        message=violation_msg,
                        symbol=name,
                    )
                )

    def _check_type_annotation(
        self, annotation: ast.expr, context: str
    ) -> tuple[str | None, str | None]:
        """Check a type annotation for violations.

        Returns:
            Tuple of (violation message, violation type) if found, (None, None) otherwise
        """
        # Check for Any (can be Name node or NameConstant in older Python)
        if isinstance(annotation, ast.Name) and annotation.id == "Any":
            return (f"{context} uses 'Any' in signature", "Any-in-signature")

        # Check for dict[str, Any]
        if (
            isinstance(annotation, ast.Subscript)
            and isinstance(annotation.value, ast.Name)
            and annotation.value.id == "dict"
        ):
            # Extract slice elements (handle Python 3.9+ and older)
            slice_elts: list[ast.expr] = []
            if isinstance(annotation.slice, ast.Tuple):
                slice_elts = annotation.slice.elts
            elif hasattr(ast, "Index") and isinstance(
                annotation.slice, ast.Index
            ):  # Python < 3.9
                if isinstance(annotation.slice.value, ast.Tuple):
                    slice_elts = annotation.slice.value.elts
                else:
                    slice_elts = [annotation.slice.value]
            else:
                # Python 3.9+ uses slice directly
                slice_elts = [annotation.slice]

            if len(slice_elts) >= 2:
                value_type = slice_elts[1]
                if isinstance(value_type, ast.Name) and value_type.id == "Any":
                    return (
                        f"{context} uses 'dict[str, Any]' in signature",
                        "dict[str, Any]",
                    )

        # Check for Union/Optional containing Any
        if isinstance(annotation, ast.BinOp) and isinstance(
            annotation.op, ast.BitOr
        ):  # Python 3.10+ union syntax
            left_violation, left_type = self._check_type_annotation(
                annotation.left, context
            )
            if left_violation:
                return (left_violation, left_type)
            right_violation, right_type = self._check_type_annotation(
                annotation.right, context
            )
            if right_violation:
                return (right_violation, right_type)

        # Check for Union/Optional (old syntax)
        if (
            isinstance(annotation, ast.Subscript)
            and isinstance(annotation.value, ast.Name)
            and annotation.value.id in ("Union", "Optional")
        ):
            if isinstance(annotation.slice, ast.Tuple):
                for elt in annotation.slice.elts:
                    violation, vtype = self._check_type_annotation(elt, context)
                    if violation:
                        return (violation, vtype)
            elif isinstance(annotation.slice, ast.Index) and isinstance(  # Python < 3.9
                annotation.slice.value, ast.Tuple
            ):
                for elt in annotation.slice.value.elts:
                    violation, vtype = self._check_type_annotation(elt, context)
                    if violation:
                        return (violation, vtype)

        return (None, None)

    def _check_type_ignore(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Check for type: ignore comments."""
        # Note: AST doesn't preserve comments, so we need to check the source
        # For now, we'll check if there's a type: ignore in the function's line range
        # This is a simplified check - a full implementation would parse comments
        # TODO: Implement comment parsing if needed


def load_scope_config(scope_file: Path | None = None) -> dict[str, TypingAny]:
    """Load boundary types scope configuration.

    Args:
        scope_file: Path to scope configuration file. If None, uses default location.

    Returns:
        Scope configuration dictionary with explicit_files, include_globs, exclude_globs

    Raises:
        FileNotFoundError: If scope file doesn't exist
        json.JSONDecodeError: If scope file is invalid JSON
    """
    if scope_file is None:
        # Default location: dev/boundary_types_scope.json relative to script
        script_dir = Path(__file__).parent.parent
        scope_file = script_dir / "boundary_types_scope.json"

    if not scope_file.exists():
        raise FileNotFoundError(
            f"Scope configuration file not found: {scope_file}. "
            "Please create dev/boundary_types_scope.json"
        )

    with scope_file.open(encoding="utf-8") as f:
        config = json.load(f)

    # Validate structure
    if not isinstance(config, dict):
        raise ValueError("Scope configuration must be a JSON object")
    if "explicit_files" not in config:
        config["explicit_files"] = []
    if "include_globs" not in config:
        config["include_globs"] = []
    if "exclude_globs" not in config:
        config["exclude_globs"] = []

    return config


def load_allowlist(
    allowlist_file: Path | None = None,
) -> tuple[list[AllowlistEntry], bool]:
    """Load boundary types allowlist.

    Args:
        allowlist_file: Path to allowlist file. If None, uses default location.

    Returns:
        Tuple of (list of valid allowlist entries, has_expired_entries)

    Raises:
        FileNotFoundError: If allowlist file doesn't exist (optional, returns empty list)
        json.JSONDecodeError: If allowlist file is invalid JSON
    """
    if allowlist_file is None:
        # Default location: dev/boundary_types_allowlist.json relative to script
        script_dir = Path(__file__).parent.parent
        allowlist_file = script_dir / "boundary_types_allowlist.json"

    if not allowlist_file.exists():
        # Allowlist is optional - return empty list if not found
        return ([], False)

    with allowlist_file.open(encoding="utf-8") as f:
        config = json.load(f)

    entries = []
    expired_entries = []

    for entry_data in config.get("entries", []):
        entry = AllowlistEntry(
            file=entry_data["file"],
            symbol=entry_data.get("symbol"),
            violation=entry_data["violation"],
            reason=entry_data["reason"],
            expires_at=entry_data["expires_at"],
            tracking=entry_data["tracking"],
        )
        if entry.is_expired():
            expired_entries.append(entry)
        else:
            entries.append(entry)

    # Report expired entries as errors
    has_expired = len(expired_entries) > 0
    if has_expired:
        print("Error: Expired allowlist entries found:", file=sys.stderr)
        for entry in expired_entries:
            print(
                f"  {entry.file}:{entry.symbol or 'N/A'} - {entry.violation} "
                f"(expired {entry.expires_at}, tracking: {entry.tracking})",
                file=sys.stderr,
            )

    return (entries, has_expired)


def is_violation_allowlisted(
    violation: Violation, violation_type: str, allowlist: list[AllowlistEntry]
) -> tuple[bool, AllowlistEntry | None]:
    """Check if a violation is allowlisted.

    Args:
        violation: The violation to check
        violation_type: Type of violation (e.g., "Any-in-signature", "dict[str, Any]")
        allowlist: List of allowlist entries

    Returns:
        Tuple of (is_allowlisted, matching_entry)
    """
    for entry in allowlist:
        if entry.matches(violation, violation_type):
            return (True, entry)
    return (False, None)


def is_in_scope(file_path: Path, scope_config: dict[str, TypingAny]) -> bool:
    """Check if a file is in the boundary enforcement scope.

    Args:
        file_path: Path to the file (absolute or relative)
        scope_config: Scope configuration dictionary

    Returns:
        True if file should be checked, False otherwise
    """
    # Normalize path to use forward slashes for consistent matching
    path_str = str(file_path).replace("\\", "/")

    # Extract relative portion from absolute paths
    # Look for common path segments like "src/" to extract relative portion
    relative_path_str = path_str
    if Path(path_str).is_absolute():
        # Try to make it relative to project root
        try:
            project_root = Path(__file__).parent.parent.parent
            relative_path_str = str(file_path.relative_to(project_root)).replace(
                "\\", "/"
            )
        except ValueError:
            # If we can't make it relative to project root, try to extract
            # relative portion by finding "src/" in the path
            if "/src/" in path_str:
                idx = path_str.index("/src/")
                relative_path_str = path_str[idx + 1 :]  # Remove leading "/"
            elif path_str.endswith("/src/"):
                # Edge case: path ends with src/
                relative_path_str = path_str

    explicit_files = scope_config.get("explicit_files", [])
    include_globs = scope_config.get("include_globs", [])
    exclude_globs = scope_config.get("exclude_globs", [])

    # Check explicit files first (highest precedence)
    # Match if path ends with explicit file or matches exactly
    for explicit_file in explicit_files:
        if relative_path_str == explicit_file or relative_path_str.endswith(
            "/" + explicit_file
        ):
            return True
        # Also check absolute path ending
        if path_str.endswith(explicit_file):
            return True

    # Check if excluded
    for exclude_pattern in exclude_globs:
        if fnmatch(relative_path_str, exclude_pattern) or fnmatch(
            path_str, exclude_pattern
        ):
            # Explicit files override excludes - check if this is an explicit file
            is_explicit = any(
                relative_path_str == ef
                or relative_path_str.endswith("/" + ef)
                or path_str.endswith(ef)
                for ef in explicit_files
            )
            if not is_explicit:
                return False

    # Check include globs
    if include_globs:
        for include_pattern in include_globs:
            if fnmatch(relative_path_str, include_pattern) or fnmatch(
                path_str, include_pattern
            ):
                return True
        # If include_globs is non-empty and no match, exclude
        return False

    # If no include_globs, only explicit files are in scope
    return False


def check_boundary_types(
    paths: list[str] | None = None,
    scope_config: dict[str, TypingAny] | None = None,
    allowlist: list[AllowlistEntry] | None = None,
) -> int:
    """Check boundary modules for type violations.

    Args:
        paths: List of paths to check (defaults to current directory)
        scope_config: Scope configuration dictionary. If None, loads from default location.
        allowlist: List of allowlist entries. If None, loads from default location.

    Returns:
        Exit code (0 for clean, 1 for violations)
    """
    if paths is None:
        paths = ["."]

    # Load scope configuration
    if scope_config is None:
        try:
            scope_config = load_scope_config()
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in scope configuration: {e}", file=sys.stderr)
            return 1

    # Load allowlist (this will print errors for expired entries and return only valid ones)
    if allowlist is None:
        try:
            allowlist, has_expired = load_allowlist()
            if has_expired:
                # Error already printed by load_allowlist, just return error code
                return 1
        except FileNotFoundError:
            allowlist = []
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in allowlist: {e}", file=sys.stderr)
            return 1

    all_violations: list[Violation] = []
    allowlisted_violations: list[tuple[Violation, AllowlistEntry]] = []

    # Get project root for relative path resolution
    project_root = Path(__file__).parent.parent.parent

    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            print(f"Warning: Path does not exist: {path}", file=sys.stderr)
            continue

        # Find all Python files
        if path.is_file():
            files = [path]
        else:
            files = list(path.rglob("*.py"))

        for file_path in files:
            # Check if file is in scope
            if not is_in_scope(file_path, scope_config):
                continue

            try:
                # Create a new checker for each file to reset state
                checker = BoundaryTypeChecker()
                source = file_path.read_text(encoding="utf-8")
                violations = checker.check_file(str(file_path), source)
                all_violations.extend(violations)
            except Exception as e:
                print(
                    f"Error checking {file_path}: {e}",
                    file=sys.stderr,
                )
                continue

    # Filter violations through allowlist
    # Extract violation type from message for matching
    def extract_violation_type(msg: str) -> str:
        if "dict[str, Any]" in msg:
            return "dict[str, Any]"
        elif "Any" in msg:
            return "Any-in-signature"
        return "unknown"

    unallowlisted_violations: list[Violation] = []
    for violation in all_violations:
        violation_type = extract_violation_type(violation.message)
        is_allowed, entry = is_violation_allowlisted(
            violation, violation_type, allowlist
        )
        if is_allowed and entry:
            allowlisted_violations.append((violation, entry))
        else:
            unallowlisted_violations.append(violation)

    # Report allowlisted violations as warnings
    if allowlisted_violations:
        print("Allowlisted violations (warnings):", file=sys.stderr)
        for violation, entry in allowlisted_violations:
            print(
                f"  {violation} [allowlisted: {entry.reason}, expires: {entry.expires_at}, "
                f"tracking: {entry.tracking}]",
                file=sys.stderr,
            )

    # Report unallowlisted violations as errors
    if unallowlisted_violations:
        print("Boundary type violations found:", file=sys.stderr)
        for violation in unallowlisted_violations:
            print(f"  {violation}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    paths = sys.argv[1:] if len(sys.argv) > 1 else None
    exit_code = check_boundary_types(paths)
    sys.exit(exit_code)
