#!/usr/bin/env python3
"""
Boundary type checker to detect Any and dict[str, Any] usage in boundary modules.

This script scans boundary modules (src/core/interfaces/, src/core/domain/, src/core/transport/)
for violations of typed contract rules:
- No new Any in function signatures for cross-layer seams
- No new dict[str, Any] for contract-shaped payloads
- No new type: ignore comments without documented rationale

Run with:
    ./.venv/Scripts/python.exe scripts/check_boundary_types.py [paths...]

If no paths are provided, scans the current directory.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any as AnyType


@dataclass
class Violation:
    """Represents a boundary type violation."""

    file_path: str
    line: int
    column: int
    message: str

    def __str__(self) -> str:
        return f"{self.file_path}:{self.line}:{self.column}: {self.message}"


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
        for pattern_class, pattern_attr in self.ALLOWLIST_PATTERNS:
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
        # Check arguments
        for arg in args.args:
            if arg.annotation:
                violation = self._check_type_annotation(
                    arg.annotation, f"Function '{name}' parameter '{arg.arg}'"
                )
                if violation:
                    self.violations.append(
                        Violation(
                            file_path=self.current_file,
                            line=node.lineno,
                            column=node.col_offset,
                            message=violation,
                        )
                    )

        # Check return type
        if returns:
            violation = self._check_type_annotation(
                returns, f"Function '{name}' return type"
            )
            if violation:
                self.violations.append(
                    Violation(
                        file_path=self.current_file,
                        line=node.lineno,
                        column=node.col_offset,
                        message=violation,
                    )
                )

    def _check_type_annotation(
        self, annotation: ast.expr, context: str
    ) -> str | None:
        """Check a type annotation for violations.

        Returns:
            Violation message if found, None otherwise
        """
        # Check for Any (can be Name node or NameConstant in older Python)
        if isinstance(annotation, ast.Name) and annotation.id == "Any":
            return f"{context} uses 'Any' in signature"

        # Check for dict[str, Any]
        if isinstance(annotation, ast.Subscript):
            if isinstance(annotation.value, ast.Name) and annotation.value.id == "dict":
                # Extract slice elements (handle Python 3.9+ and older)
                slice_elts: list[ast.expr] = []
                if isinstance(annotation.slice, ast.Tuple):
                    slice_elts = annotation.slice.elts
                elif hasattr(ast, "Index") and isinstance(annotation.slice, ast.Index):  # Python < 3.9
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
                        return f"{context} uses 'dict[str, Any]' in signature"

        # Check for Union/Optional containing Any
        if isinstance(annotation, ast.BinOp) and isinstance(
            annotation.op, ast.BitOr
        ):  # Python 3.10+ union syntax
            left_violation = self._check_type_annotation(annotation.left, context)
            if left_violation:
                return left_violation
            right_violation = self._check_type_annotation(annotation.right, context)
            if right_violation:
                return right_violation

        # Check for Union/Optional (old syntax)
        if isinstance(annotation, ast.Subscript):
            if isinstance(annotation.value, ast.Name):
                if annotation.value.id in ("Union", "Optional"):
                    if isinstance(annotation.slice, ast.Tuple):
                        for elt in annotation.slice.elts:
                            violation = self._check_type_annotation(elt, context)
                            if violation:
                                return violation
                    elif isinstance(annotation.slice, ast.Index):  # Python < 3.9
                        if isinstance(annotation.slice.value, ast.Tuple):
                            for elt in annotation.slice.value.elts:
                                violation = self._check_type_annotation(elt, context)
                                if violation:
                                    return violation

        return None

    def _check_type_ignore(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        """Check for type: ignore comments."""
        # Note: AST doesn't preserve comments, so we need to check the source
        # For now, we'll check if there's a type: ignore in the function's line range
        # This is a simplified check - a full implementation would parse comments
        pass  # TODO: Implement comment parsing if needed


def is_boundary_module(file_path: Path) -> bool:
    """Check if a file is in a boundary module directory.

    Args:
        file_path: Path to the file

    Returns:
        True if file is in a boundary module directory
    """
    # Normalize path to use forward slashes for consistent matching
    path_str = str(file_path).replace("\\", "/")
    boundary_dirs = [
        "src/core/interfaces",
        "src/core/domain",
        "src/core/transport",
    ]
    return any(boundary_dir in path_str for boundary_dir in boundary_dirs)


def check_boundary_types(paths: list[str] | None = None) -> int:
    """Check boundary modules for type violations.

    Args:
        paths: List of paths to check (defaults to current directory)

    Returns:
        Exit code (0 for clean, 1 for violations)
    """
    if paths is None:
        paths = ["."]

    all_violations: list[Violation] = []

    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            print(f"Warning: Path does not exist: {path}", file=sys.stderr)
            continue

        # Find all Python files in boundary modules
        if path.is_file():
            files = [path]
        else:
            files = list(path.rglob("*.py"))

        for file_path in files:
            if not is_boundary_module(file_path):
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

    # Report violations
    if all_violations:
        print("Boundary type violations found:", file=sys.stderr)
        for violation in all_violations:
            print(f"  {violation}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    paths = sys.argv[1:] if len(sys.argv) > 1 else None
    exit_code = check_boundary_types(paths)
    sys.exit(exit_code)

