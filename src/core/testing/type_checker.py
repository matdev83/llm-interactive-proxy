"""
Development-time type checker for async/sync patterns in tests.

This module provides utilities that can be run during development or CI
to catch potential coroutine warning issues before they occur in tests.
"""

from __future__ import annotations

import ast
import inspect
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AsyncSyncPatternChecker:
    """
    Static analyzer that checks for common patterns that lead to coroutine warnings.

    This can be integrated into CI/CD or run as a pre-commit hook to catch
    issues before they make it into the codebase.
    """

    def __init__(self) -> None:
        self.issues: list[str] = []

    def check_file(self, file_path: Path) -> list[str]:
        """
        Check a Python file for async/sync pattern issues.

        Args:
            file_path: Path to the Python file to check

        Returns:
            List of issue descriptions found in the file
        """
        self.issues = []

        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            tree = ast.parse(content, filename=str(file_path))
            self._check_ast_node(tree, str(file_path))

        except (SyntaxError, OSError) as e:
            self.issues.append(f"Error parsing {file_path}: {e}")

        return self.issues.copy()

    def check_directory(
        self, directory: Path, pattern: str = "test_*.py"
    ) -> dict[str, list[str]]:
        """
        Check all test files in a directory for issues.

        Args:
            directory: Directory to scan
            pattern: File pattern to match (default: test_*.py)

        Returns:
            Dictionary mapping file paths to lists of issues
        """
        results = {}

        for file_path in directory.rglob(pattern):
            if file_path.is_file():
                issues = self.check_file(file_path)
                if issues:
                    results[str(file_path)] = issues

        return results

    def _check_ast_node(self, node: ast.AST, filename: str) -> None:
        """Check an AST node for issues."""
        if isinstance(node, ast.FunctionDef):
            self._check_function_def(node, filename)
        elif isinstance(node, ast.ClassDef):
            self._check_class_def(node, filename)
        elif isinstance(node, ast.Assign):
            self._check_assignment(node, filename)
        elif isinstance(node, ast.Call):
            self._check_function_call(node, filename)

        # Recursively check child nodes
        for child in ast.iter_child_nodes(node):
            self._check_ast_node(child, filename)

    def _check_function_def(self, node: ast.FunctionDef, filename: str) -> None:
        """Check function definitions for issues."""
        # Check for test functions that might have async issues
        if node.name.startswith("test_"):
            # Look for AsyncMock usage in test functions
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and child.id == "AsyncMock":
                    self.issues.append(
                        f"{filename}:{node.lineno}: Test function '{node.name}' uses AsyncMock. "
                        f"Consider using EnforcedMockFactory methods to avoid coroutine warnings."
                    )

    def _check_class_def(self, node: ast.ClassDef, filename: str) -> None:
        """Check class definitions for issues."""
        # Check for test stages that don't inherit from ValidatedTestStage
        if any(
            base.id == "InitializationStage"
            for base in node.bases
            if isinstance(base, ast.Name)
        ) and ("TestStage" in node.name or "MockStage" in node.name):
            # Check if it also inherits from ValidatedTestStage
            has_validated_base = any(
                base.id == "ValidatedTestStage"
                for base in node.bases
                if isinstance(base, ast.Name)
            )
            if not has_validated_base:
                self.issues.append(
                    f"{filename}:{node.lineno}: Test stage '{node.name}' should inherit from "
                    f"ValidatedTestStage instead of InitializationStage directly to get "
                    f"automatic validation against coroutine warnings."
                )

    def _check_assignment(self, node: ast.Assign, filename: str) -> None:
        """Check assignments for problematic patterns."""
        # Check for direct AsyncMock assignments in test code
        if (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "AsyncMock"
        ):
            # Check if this is for a session service or similar
            for target in node.targets:
                if isinstance(target, ast.Name) and "session" in target.id.lower():
                    self.issues.append(
                        f"{filename}:{node.lineno}: Direct AsyncMock assignment to '{target.id}'. "
                        f"For session services, use EnforcedMockFactory.create_session_service_mock() "
                        f"to avoid coroutine warnings."
                    )

    def _check_function_call(self, node: ast.Call, filename: str) -> None:
        """Check function calls for problematic patterns."""
        # Check for calls to add_instance with AsyncMock
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_instance"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Call)
            and isinstance(node.args[1].func, ast.Name)
            and node.args[1].func.id == "AsyncMock"
        ):
            self.issues.append(
                f"{filename}:{node.lineno}: Registering AsyncMock directly with add_instance. "
                f"Consider using safe_register_instance() from ValidatedTestStage or "
                f"EnforcedMockFactory methods to avoid coroutine warnings."
            )


class RuntimePatternChecker:
    """
    Runtime checker that can be integrated into test fixtures to catch issues at runtime.
    """

    @staticmethod
    def check_service_registration(service_type: type, instance: Any) -> list[str]:
        """
        Check a service registration for potential issues.

        Args:
            service_type: The service type being registered
            instance: The service instance

        Returns:
            List of warning messages
        """
        warnings = []

        # Check for session service issues
        if (
            hasattr(service_type, "__name__")
            and "Session" in service_type.__name__
            and hasattr(instance, "get_session")
        ):
            try:
                result = instance.get_session("test_id")
                if inspect.iscoroutine(result):
                    result.close()  # Clean up
                    warnings.append(
                        f"Session service {service_type.__name__}.get_session() returns a coroutine "
                        f"but should return a Session object directly. This will cause coroutine warnings."
                    )
            except (AttributeError, TypeError) as e:
                # Can't test, skip
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Could not check service registration for {service_type.__name__}: {e}",
                        exc_info=True,
                    )

        # Check for AsyncMock in sync contexts
        from unittest.mock import AsyncMock

        if isinstance(instance, AsyncMock):
            sync_method_names = ["get_session", "add_interaction", "get_interactions"]
            for method_name in sync_method_names:
                if hasattr(instance, method_name):
                    method = getattr(instance, method_name)
                    if isinstance(method, AsyncMock):
                        warnings.append(
                            f"Method {service_type.__name__}.{method_name} is AsyncMock but "
                            f"should be synchronous. Use MagicMock or mark as sync."
                        )

        return warnings

    @staticmethod
    def validate_test_app(app: Any) -> list[str]:
        """
        Validate a test application for potential coroutine warning issues.

        Args:
            app: The FastAPI test application

        Returns:
            List of warning messages
        """
        warnings = []

        # Check service provider if available
        if hasattr(app.state, "service_provider"):
            sp = app.state.service_provider

            # Try to resolve known problematic services
            try:
                from src.core.interfaces.session_service_interface import (
                    ISessionService,
                )

                session_service = sp.get_service(ISessionService)
                if session_service:
                    service_warnings = RuntimePatternChecker.check_service_registration(
                        ISessionService, session_service
                    )
                    warnings.extend(service_warnings)
            except (AttributeError, TypeError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Could not validate test app: {e}", exc_info=True)

        return warnings


def create_pre_commit_hook() -> str:
    """
    Create a pre-commit hook script that checks for async/sync pattern issues.

    Returns:
        The shell script content for the pre-commit hook
    """
    return """#!/bin/bash
# Pre-commit hook to check for async/sync pattern issues

python -c "
import sys
from pathlib import Path
from src.core.testing.type_checker import AsyncSyncPatternChecker

checker = AsyncSyncPatternChecker()
issues_found = False

# Check staged files
import subprocess
result = subprocess.run(['git', 'diff', '--cached', '--name-only', '--diff-filter=ACM'], 
                       capture_output=True, text=True)
staged_files = result.stdout.strip().split('\\n')

for file_path in staged_files:
    if file_path.endswith('.py') and ('test_' in file_path or file_path.startswith('test')):
        path = Path(file_path)
        if path.exists():
            issues = checker.check_file(path)
            if issues:
                issues_found = True
                print(f'Issues found in {file_path}:')
                for issue in issues:
                    print(f'  - {issue}')
                print()

if issues_found:
    print('Async/sync pattern issues found. Please fix before committing.')
    print('Consider using:')
    print('  - ValidatedTestStage instead of InitializationStage')
    print('  - EnforcedMockFactory.create_*_mock() methods')
    print('  - SafeAsyncMockWrapper for mixed async/sync interfaces')
    sys.exit(1)
else:
    print('No async/sync pattern issues found.')
"
"""


if __name__ == "__main__":
    # CLI interface for running the checker
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Check for async/sync pattern issues")
    parser.add_argument("path", help="File or directory to check")
    parser.add_argument(
        "--pattern", default="test_*.py", help="File pattern for directory scanning"
    )

    args = parser.parse_args()

    checker = AsyncSyncPatternChecker()
    path = Path(args.path)

    if path.is_file():
        issues = checker.check_file(path)
        if issues:
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"Issues found in {path}:")
                for issue in issues:
                    logger.info(f"  - {issue}")
            sys.exit(1)
    elif path.is_dir():
        results = checker.check_directory(path, args.pattern)
        if results:
            if logger.isEnabledFor(logging.INFO):
                logger.info("Issues found:")
                for file_path, issues in results.items():
                    logger.info(f"\n{file_path}:")
                    for issue in issues:
                        logger.info(f"  - {issue}")
            sys.exit(1)
    else:
        logger.error(f"Path {path} does not exist")
        sys.exit(1)

    if logger.isEnabledFor(logging.INFO):
        logger.info("No issues found!")
