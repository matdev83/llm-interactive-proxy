#!/usr/bin/env python3
"""
Architectural linter to detect SOLID violations in code.

This tool can be run as part of CI/CD to catch architectural violations
before they make it into the codebase.
"""

import ast
import os
import sys
from pathlib import Path


class ArchitecturalViolation:
    """Represents an architectural violation."""

    def __init__(
        self,
        file_path: str,
        line: int,
        column: int,
        message: str,
        severity: str = "error",
    ):
        self.file_path = file_path
        self.line = line
        self.column = column
        self.message = message
        self.severity = severity

    def __str__(self):
        return f"{self.file_path}:{self.line}:{self.column}: {self.severity}: {self.message}"


class SOLIDViolationDetector(ast.NodeVisitor):
    """AST visitor to detect SOLID principle violations."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.violations: list[ArchitecturalViolation] = []
        self.is_domain_layer = "/domain/" in file_path
        self.is_service_layer = "/services/" in file_path
        self.is_interface_layer = "/interfaces/" in file_path
        self.current_class = None
        self.current_method = None
        self.imports = {}  # Track imports for later analysis
        self.class_attributes = set()  # Track class attributes
        self.class_methods = set()  # Track class methods
        self.static_methods = set()  # Track static methods

    def visit_Import(  # noqa: N802 - AST visitor API requires this name
        self, node: ast.Import
    ):
        """Visit import statements."""
        for name in node.names:
            self.imports[name.asname or name.name] = name.name
        self.generic_visit(node)

    def visit_ImportFrom(  # noqa: N802 - AST visitor API requires this name
        self, node: ast.ImportFrom
    ):
        """Visit from-import statements."""
        if node.module:
            # Check for direct imports from implementation modules instead of interfaces
            if (
                self.is_service_layer
                and not self.is_interface_layer
                and not node.module.endswith("_interface")
                and not node.module.endswith(".interfaces")
                and "interfaces" not in node.module
                and any(
                    name.name.startswith("I") and name.name[1].isupper()
                    for name in node.names
                )
            ):
                self.violations.append(
                    ArchitecturalViolation(
                        self.file_path,
                        node.lineno,
                        node.col_offset,
                        f"Import interfaces from interface modules, not from '{node.module}'",
                        "warning",
                    )
                )

            for name in node.names:
                # Store the full import path for later analysis
                full_name = f"{node.module}.{name.name}" if node.module else name.name
                self.imports[name.asname or name.name] = full_name

        self.generic_visit(node)

    def visit_ClassDef(  # noqa: N802 - AST visitor API requires this name
        self, node: ast.ClassDef
    ):
        """Visit class definitions."""
        old_class = self.current_class
        self.current_class = node.name
        self.class_attributes = set()
        self.class_methods = set()
        self.static_methods = set()

        # Check for domain layer violations
        if self.is_domain_layer:
            self._check_domain_class_violations(node)

        # Check for service layer violations
        if self.is_service_layer:
            self._check_service_class_violations(node)

        # Process class body to collect attributes and methods
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        self.class_attributes.add(target.id)
            elif isinstance(item, ast.FunctionDef):
                self.class_methods.add(item.name)
                # Check for static methods
                if any(
                    isinstance(d, ast.Name) and d.id == "staticmethod"
                    for d in item.decorator_list
                ):
                    self.static_methods.add(item.name)

        # Check for singleton pattern
        self._check_singleton_pattern(node)

        self.generic_visit(node)
        self.current_class = old_class

    def visit_FunctionDef(  # noqa: N802 - AST visitor API requires this name
        self, node: ast.FunctionDef
    ):
        """Visit function definitions."""
        old_method = self.current_method
        self.current_method = node.name

        # Check for service layer violations
        if self.is_service_layer:
            self._check_service_method_violations(node)

            # Check for static methods in service classes
            if (
                self.current_class
                and any(
                    isinstance(d, ast.Name) and d.id == "staticmethod"
                    for d in node.decorator_list
                )
                and not node.name.startswith("_")  # Allow private static methods
            ):
                self.violations.append(
                    ArchitecturalViolation(
                        self.file_path,
                        node.lineno,
                        node.col_offset,
                        f"Avoid static methods in service classes: {self.current_class}.{node.name}. Use proper DI instead.",
                        "warning",
                    )
                )

        self.generic_visit(node)
        self.current_method = old_method

    def visit_Attribute(  # noqa: N802 - AST visitor API requires this name
        self, node: ast.Attribute
    ):
        """Visit attribute access."""
        # Check for direct app.state access
        if self._is_app_state_access(node) and not self._has_dip_noqa_comment(node):
            # Add appropriate violation based on layer
            if self.is_domain_layer:
                self.violations.append(
                    ArchitecturalViolation(
                        self.file_path,
                        node.lineno,
                        node.col_offset,
                        "Domain layer should not directly access app.state. Use IApplicationState through DI.",
                        "error",
                    )
                )
            elif self.is_service_layer:
                self.violations.append(
                    ArchitecturalViolation(
                        self.file_path,
                        node.lineno,
                        node.col_offset,
                        "Service layer should use IApplicationState abstraction instead of direct app.state access.",
                        "warning",
                    )
                )

        # Check for context.app_state access
        if self._is_context_app_state_access(node):
            self.violations.append(
                ArchitecturalViolation(
                    self.file_path,
                    node.lineno,
                    node.col_offset,
                    "Use IApplicationState service instead of context.app_state direct access.",
                    "error",
                )
            )

        # Check for singleton access patterns
        if (
            isinstance(node.value, ast.Name)
            and node.attr == "instance"
            and node.value.id in self.imports
        ):
            self.violations.append(
                ArchitecturalViolation(
                    self.file_path,
                    node.lineno,
                    node.col_offset,
                    f"Avoid singleton pattern access: {node.value.id}.instance. Use dependency injection instead.",
                    "warning",
                )
            )

        self.generic_visit(node)

    def visit_Call(  # noqa: N802 - AST visitor API requires this name
        self, node: ast.Call
    ):
        """Visit function calls."""
        # Check for hasattr/getattr/setattr on app.state
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in ["hasattr", "getattr", "setattr"]
            and len(node.args) >= 2
        ):

            first_arg = node.args[0]
            second_arg = node.args[1]

            if (
                isinstance(second_arg, ast.Constant)
                and isinstance(second_arg.value, str)
                and "state" in second_arg.value
                and self._references_app_object(first_arg)
                and not self._has_dip_noqa_comment_for_call(node)
            ):

                self.violations.append(
                    ArchitecturalViolation(
                        self.file_path,
                        node.lineno,
                        node.col_offset,
                        f"Avoid {node.func.id}() on app.state. Use IApplicationState service.",
                        "warning",
                    )
                )

        # Check for singleton getInstance() pattern
        if isinstance(node.func, ast.Attribute) and node.func.attr in [
            "getInstance",
            "get_instance",
        ]:
            self.violations.append(
                ArchitecturalViolation(
                    self.file_path,
                    node.lineno,
                    node.col_offset,
                    f"Avoid singleton pattern: {node.func.attr}(). Use dependency injection instead.",
                    "warning",
                )
            )

        self.generic_visit(node)

    def _is_app_state_access(self, node: ast.Attribute) -> bool:
        """Check if this is direct app.state access."""
        if node.attr == "state":
            if isinstance(node.value, ast.Attribute) and node.value.attr == "app":
                return True
            if isinstance(node.value, ast.Name) and "app" in node.value.id.lower():
                return True
        return False

    def _is_context_app_state_access(self, node: ast.Attribute) -> bool:
        """Check if this is context.app_state access."""
        return (
            node.attr == "app_state"
            and isinstance(node.value, ast.Name)
            and node.value.id == "context"
        )

    def _references_app_object(self, node: ast.AST) -> bool:
        """Check if a node references an app object."""
        if isinstance(node, ast.Attribute):
            return node.attr == "app" or self._references_app_object(node.value)
        if isinstance(node, ast.Name):
            return "app" in node.id.lower()
        return False

    def _has_dip_noqa_comment(self, node: ast.Attribute) -> bool:
        """Check if the node has a DIP noqa comment."""
        # This is a simplified check - in a real implementation you'd need to parse comments
        # For now, we'll check if the line contains specific noqa patterns
        try:
            with open(self.file_path, encoding="utf-8") as f:
                lines = f.readlines()
                if node.lineno - 1 < len(lines):
                    line = lines[node.lineno - 1]
                    return "noqa: DIP-violation" in line or "DIP-violation-" in line
        except Exception:
            pass
        return False

    def _has_dip_noqa_comment_for_call(self, node: ast.Call) -> bool:
        """Check if the call node has a DIP noqa comment."""
        # This is a simplified check - in a real implementation you'd need to parse comments
        # For now, we'll check if the line contains specific noqa patterns
        try:
            with open(self.file_path, encoding="utf-8") as f:
                lines = f.readlines()
                if node.lineno - 1 < len(lines):
                    line = lines[node.lineno - 1]
                    return "noqa: DIP-violation" in line or "DIP-violation-" in line
        except Exception:
            pass
        return False

    def _check_domain_class_violations(self, node: ast.ClassDef):
        """Check for domain layer class violations."""
        # Domain classes should not have web framework dependencies
        for base in node.bases:
            if isinstance(base, ast.Name) and any(
                framework in base.id.lower()
                for framework in ["fastapi", "flask", "django", "starlette"]
            ):
                self.violations.append(
                    ArchitecturalViolation(
                        self.file_path,
                        node.lineno,
                        node.col_offset,
                        f"Domain class {node.name} should not inherit from web framework classes.",
                        "error",
                    )
                )

    def _check_service_class_violations(self, node: ast.ClassDef):
        """Check for service layer class violations."""
        # Service classes should implement interfaces
        if not node.name.startswith("_") and not node.name.startswith("Test"):
            implements_interface = False

            # Check class bases for interface implementation
            for base in node.bases:
                if (
                    isinstance(base, ast.Name)
                    and base.id.startswith("I")
                    and base.id[1].isupper()
                ):
                    implements_interface = True
                    break

                    # Check if this is an abstract base class (might not need to implement an interface)
            is_abstract = False
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and any(
                    isinstance(d, ast.Name) and d.id == "abstractmethod"
                    for d in item.decorator_list
                ):
                    is_abstract = True
                    break

            # If not abstract and not implementing an interface, flag it
            if (
                not is_abstract
                and not implements_interface
                and not "Exception" in node.name
            ):
                self.violations.append(
                    ArchitecturalViolation(
                        self.file_path,
                        node.lineno,
                        node.col_offset,
                        f"Service class {node.name} should implement an interface.",
                        "warning",
                    )
                )

    def _check_service_method_violations(self, node: ast.FunctionDef):
        """Check for service layer method violations."""
        # Service methods should use dependency injection
        if node.name.startswith("_"):
            return  # Skip private methods

        # Check if method has proper DI parameters
        has_di_params = any(
            arg.annotation
            and isinstance(arg.annotation, ast.Name)
            and arg.annotation.id.startswith("I")
            and arg.annotation.id[1].isupper()
            for arg in node.args.args[1:]  # Skip 'self'
        )

        # If method accesses state but doesn't have DI params, flag it
        state_access_found = False
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute) and child.attr in [
                "state",
                "app_state",
            ]:
                state_access_found = True
                break

        if state_access_found and not has_di_params:
            self.violations.append(
                ArchitecturalViolation(
                    self.file_path,
                    node.lineno,
                    node.col_offset,
                    f"Method {node.name} accesses state but doesn't use dependency injection.",
                    "warning",
                )
            )

    def _check_singleton_pattern(self, node: ast.ClassDef):
        """Check for singleton pattern implementation."""
        # Check for class-level _instance attribute
        has_instance_attr = "_instance" in self.class_attributes

        # Check for getInstance or similar methods
        has_get_instance_method = any(
            method in self.class_methods
            for method in ["getInstance", "get_instance", "instance"]
        )

        # Check for static methods that return self
        has_static_instance_method = bool(self.static_methods)

        if has_instance_attr and (
            has_get_instance_method or has_static_instance_method
        ):
            self.violations.append(
                ArchitecturalViolation(
                    self.file_path,
                    node.lineno,
                    node.col_offset,
                    f"Class {node.name} appears to implement a singleton pattern. Use dependency injection instead.",
                    "warning",
                )
            )


def lint_file(file_path: str) -> list[ArchitecturalViolation]:
    """Lint a single Python file for architectural violations."""
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        tree = ast.parse(content, filename=file_path)
        detector = SOLIDViolationDetector(file_path)
        detector.visit(tree)

        return detector.violations

    except SyntaxError as e:
        return [
            ArchitecturalViolation(
                file_path,
                e.lineno or 0,
                e.offset or 0,
                f"Syntax error: {e.msg}",
                "error",
            )
        ]
    except Exception as e:
        return [
            ArchitecturalViolation(
                file_path, 0, 0, f"Failed to parse file: {e}", "error"
            )
        ]


def lint_directory(
    directory: str, patterns: list[str] | None = None
) -> list[ArchitecturalViolation]:
    """Lint all Python files in a directory."""
    if patterns is None:
        patterns = ["**/*.py"]

    violations = []
    directory_path = Path(directory)

    for pattern in patterns:
        for file_path in directory_path.glob(pattern):
            if file_path.is_file():
                file_violations = lint_file(str(file_path))
                violations.extend(file_violations)

    return violations


def main():
    """Main entry point for the architectural linter."""
    if len(sys.argv) < 2:
        print("Usage: python architectural_linter_enhanced.py <directory_or_file>")
        sys.exit(1)

    target = sys.argv[1]

    if os.path.isfile(target):
        violations = lint_file(target)
    elif os.path.isdir(target):
        violations = lint_directory(target)
    else:
        print(f"Error: {target} is not a valid file or directory")
        sys.exit(1)

    # Group violations by severity
    errors = [v for v in violations if v.severity == "error"]
    warnings = [v for v in violations if v.severity == "warning"]

    # Print results
    if violations:
        print(f"Found {len(violations)} architectural violations:")
        print()

        if errors:
            print("ERRORS:")
            for violation in errors:
                print(f"  {violation}")
            print()

        if warnings:
            print("WARNINGS:")
            for violation in warnings:
                print(f"  {violation}")
            print()

        # Exit with error code if there are errors
        if errors:
            print(f"[ERROR] {len(errors)} errors found. Please fix before committing.")
            sys.exit(1)
        else:
            print(
                f"[WARNING] {len(warnings)} warnings found. Consider addressing these."
            )
            sys.exit(0)
    else:
        print("[OK] No architectural violations found!")
        sys.exit(0)


if __name__ == "__main__":
    main()
