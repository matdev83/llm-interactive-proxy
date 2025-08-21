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
from typing import List, Dict, Any


class ArchitecturalViolation:
    """Represents an architectural violation."""
    
    def __init__(self, file_path: str, line: int, column: int, message: str, severity: str = "error"):
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
        self.violations: List[ArchitecturalViolation] = []
        self.is_domain_layer = '/domain/' in file_path
        self.is_service_layer = '/services/' in file_path
        self.current_class = None
        self.current_method = None
    
    def visit_ClassDef(self, node: ast.ClassDef):
        """Visit class definitions."""
        old_class = self.current_class
        self.current_class = node.name
        
        # Check for domain layer violations
        if self.is_domain_layer:
            self._check_domain_class_violations(node)
        
        self.generic_visit(node)
        self.current_class = old_class
    
    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Visit function definitions."""
        old_method = self.current_method
        self.current_method = node.name
        
        # Check for service layer violations
        if self.is_service_layer:
            self._check_service_method_violations(node)
        
        self.generic_visit(node)
        self.current_method = old_method
    
    def visit_Attribute(self, node: ast.Attribute):
        """Visit attribute access."""
        # Check for direct app.state access
        if self._is_app_state_access(node):
            if self.is_domain_layer:
                self.violations.append(ArchitecturalViolation(
                    self.file_path,
                    node.lineno,
                    node.col_offset,
                    "Domain layer should not directly access app.state. Use IApplicationState through DI.",
                    "error"
                ))
            elif self.is_service_layer:
                self.violations.append(ArchitecturalViolation(
                    self.file_path,
                    node.lineno,
                    node.col_offset,
                    "Service layer should use IApplicationState abstraction instead of direct app.state access.",
                    "warning"
                ))
        
        # Check for context.app_state access
        if self._is_context_app_state_access(node):
            self.violations.append(ArchitecturalViolation(
                self.file_path,
                node.lineno,
                node.col_offset,
                "Use IApplicationState service instead of context.app_state direct access.",
                "error"
            ))
        
        self.generic_visit(node)
    
    def visit_Call(self, node: ast.Call):
        """Visit function calls."""
        # Check for hasattr/getattr/setattr on app.state
        if isinstance(node.func, ast.Name) and node.func.id in ['hasattr', 'getattr', 'setattr']:
            if len(node.args) >= 2:
                first_arg = node.args[0]
                second_arg = node.args[1]
                
                if (isinstance(second_arg, ast.Constant) and 
                    isinstance(second_arg.value, str) and
                    'state' in second_arg.value):
                    
                    if self._references_app_object(first_arg):
                        self.violations.append(ArchitecturalViolation(
                            self.file_path,
                            node.lineno,
                            node.col_offset,
                            f"Avoid {node.func.id}() on app.state. Use IApplicationState service.",
                            "warning"
                        ))
        
        self.generic_visit(node)
    
    def _is_app_state_access(self, node: ast.Attribute) -> bool:
        """Check if this is direct app.state access."""
        if node.attr == 'state':
            if isinstance(node.value, ast.Attribute) and node.value.attr == 'app':
                return True
            if isinstance(node.value, ast.Name) and 'app' in node.value.id.lower():
                return True
        return False
    
    def _is_context_app_state_access(self, node: ast.Attribute) -> bool:
        """Check if this is context.app_state access."""
        if node.attr == 'app_state':
            if isinstance(node.value, ast.Name) and node.value.id == 'context':
                return True
        return False
    
    def _references_app_object(self, node: ast.AST) -> bool:
        """Check if a node references an app object."""
        if isinstance(node, ast.Attribute):
            return node.attr == 'app' or self._references_app_object(node.value)
        if isinstance(node, ast.Name):
            return 'app' in node.id.lower()
        return False
    
    def _check_domain_class_violations(self, node: ast.ClassDef):
        """Check for domain layer class violations."""
        # Domain classes should not have web framework dependencies
        for base in node.bases:
            if isinstance(base, ast.Name):
                if any(framework in base.id.lower() for framework in ['fastapi', 'flask', 'django']):
                    self.violations.append(ArchitecturalViolation(
                        self.file_path,
                        node.lineno,
                        node.col_offset,
                        f"Domain class {node.name} should not inherit from web framework classes.",
                        "error"
                    ))
    
    def _check_service_method_violations(self, node: ast.FunctionDef):
        """Check for service layer method violations."""
        # Service methods should use dependency injection
        if node.name.startswith('_'):
            return  # Skip private methods
        
        # Check if method has proper DI parameters
        has_di_params = any(
            arg.annotation and isinstance(arg.annotation, ast.Name) and 
            arg.annotation.id.startswith('I')
            for arg in node.args.args[1:]  # Skip 'self'
        )
        
        # If method accesses state but doesn't have DI params, flag it
        state_access_found = False
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute) and child.attr in ['state', 'app_state']:
                state_access_found = True
                break
        
        if state_access_found and not has_di_params:
            self.violations.append(ArchitecturalViolation(
                self.file_path,
                node.lineno,
                node.col_offset,
                f"Method {node.name} accesses state but doesn't use dependency injection.",
                "warning"
            ))


def lint_file(file_path: str) -> List[ArchitecturalViolation]:
    """Lint a single Python file for architectural violations."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        tree = ast.parse(content, filename=file_path)
        detector = SOLIDViolationDetector(file_path)
        detector.visit(tree)
        
        return detector.violations
    
    except SyntaxError as e:
        return [ArchitecturalViolation(
            file_path, e.lineno or 0, e.offset or 0, 
            f"Syntax error: {e.msg}", "error"
        )]
    except Exception as e:
        return [ArchitecturalViolation(
            file_path, 0, 0, 
            f"Failed to parse file: {e}", "error"
        )]


def lint_directory(directory: str, patterns: List[str] = None) -> List[ArchitecturalViolation]:
    """Lint all Python files in a directory."""
    if patterns is None:
        patterns = ['**/*.py']
    
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
        print("Usage: python architectural_linter.py <directory_or_file>")
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
            print(f"[WARNING] {len(warnings)} warnings found. Consider addressing these.")
            sys.exit(0)
    else:
        print("[OK] No architectural violations found!")
        sys.exit(0)


if __name__ == "__main__":
    main()