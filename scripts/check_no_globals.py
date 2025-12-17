#!/usr/bin/env python3
"""Check that tool-call reactor subsystem doesn't use global streaming registry.

This script scans the tool-call reactor subsystem directory for imports or calls
to get_global_streaming_context_registry() to enforce the "no global state required"
constraint.
"""

import ast
import sys
from pathlib import Path


def check_file(file_path: Path) -> list[str]:
    """Check a single Python file for global registry access violations.

    Args:
        file_path: Path to the Python file to check.

    Returns:
        List of violation messages (empty if no violations found).
    """
    violations: list[str] = []

    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
            tree = ast.parse(content, filename=str(file_path))
    except SyntaxError as e:
        return [f"Syntax error in {file_path}: {e}"]

    # Check for imports of get_global_streaming_context_registry
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "get_global_streaming_context_registry" in alias.name:
                    violations.append(
                        f"{file_path}:{node.lineno}: Import of get_global_streaming_context_registry"
                    )
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and "get_global_streaming_context_registry" in str(node.module)
        ):
            for alias in node.names:
                if alias.name == "get_global_streaming_context_registry":
                    violations.append(
                        f"{file_path}:{node.lineno}: Import of get_global_streaming_context_registry"
                    )

    # Check for calls to get_global_streaming_context_registry
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id == "get_global_streaming_context_registry":
                    violations.append(
                        f"{file_path}:{node.lineno}: Direct call to get_global_streaming_context_registry()"
                    )
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "get_global_streaming_context_registry"
            ):
                violations.append(
                    f"{file_path}:{node.lineno}: Call to get_global_streaming_context_registry()"
                )

    return violations


def main() -> int:
    """Main entry point for the check script.

    Returns:
        Exit code: 0 if no violations, 1 if violations found.
    """
    project_root = Path(__file__).parent.parent
    subsystem_dir = project_root / "src" / "core" / "services" / "tool_call_reactor"

    if not subsystem_dir.exists():
        print(f"Warning: Subsystem directory not found: {subsystem_dir}")
        return 0

    all_violations: list[str] = []

    # Check all Python files in the subsystem directory
    for py_file in subsystem_dir.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue  # Skip __init__.py files
        violations = check_file(py_file)
        all_violations.extend(violations)

    if all_violations:
        print("ERROR: Found violations of 'no global state required' constraint:")
        print()
        for violation in all_violations:
            print(f"  {violation}")
        print()
        print(
            "The tool-call reactor subsystem must not use get_global_streaming_context_registry()."
        )
        print(
            "Use injected StreamingContextRegistry via IToolCallStreamContextResolver instead."
        )
        print()
        print("See src/core/services/tool_call_reactor/README.md for details.")
        return 1

    print(
        "OK: No global registry access violations found in tool-call reactor subsystem."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
