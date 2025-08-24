#!/usr/bin/env python
"""
Analyze Module Dependencies

This script analyzes dependencies on a specified module in the codebase.
It helps identify all imports and references to a module before removal.
"""

import ast
import os
import sys
from pathlib import Path


class ImportVisitor(ast.NodeVisitor):
    """AST visitor that finds imports of specific modules."""

    def __init__(self, target_module):
        self.target_module = target_module
        self.simple_name = target_module.split(".")[-1]
        self.imports = []

    def visit_Import(self, node):
        """Visit Import nodes."""
        for name in node.names:
            if (
                name.name == self.target_module
                or name.name == self.simple_name
                or name.name.startswith(f"{self.target_module}.")
                or (
                    self.target_module.startswith("src.")
                    and name.name == self.target_module[4:]
                )
            ):
                self.imports.append((node.lineno, f"import {name.name}"))
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        """Visit ImportFrom nodes."""
        if (
            node.module == self.target_module
            or node.module == self.simple_name
            or (node.module and node.module.startswith(f"{self.target_module}."))
            or (
                self.target_module.startswith("src.")
                and node.module == self.target_module[4:]
            )
            or (
                node.module
                and self.target_module.startswith("src.")
                and node.module == self.target_module[4:].split(".")[0]
            )
        ):
            names = ", ".join(name.name for name in node.names)
            self.imports.append((node.lineno, f"from {node.module} import {names}"))
        self.generic_visit(node)


def find_references(file_path, module_name):
    """Find references to a module in a file.

    Args:
        file_path: Path to the file
        module_name: Name of the module to find references to

    Returns:
        List of (line_number, import_statement) tuples
    """
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        tree = ast.parse(content)
        visitor = ImportVisitor(module_name)
        visitor.visit(tree)

        return visitor.imports
    except SyntaxError:
        print(f"Error parsing {file_path}")
        return []
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return []


def analyze_module_dependencies(module_name, directory="src"):
    """Analyze dependencies on a module.

    Args:
        module_name: Name of the module to analyze (without .py extension)
        directory: Directory to search in

    Returns:
        Dictionary mapping file paths to lists of (line_number, import_statement) tuples
    """
    dependencies = {}

    # Check if directory exists
    if not os.path.isdir(directory):
        print(f"Directory not found: {directory}")
        return dependencies

    # Look for .py files recursively
    for path in Path(directory).rglob("*.py"):
        if path.is_file():  # Make sure it's a file, not a directory
            references = find_references(path, module_name)
            if references:
                dependencies[str(path)] = references

    return dependencies


def print_dependencies(dependencies):
    """Print dependencies in a readable format.

    Args:
        dependencies: Dictionary mapping file paths to lists of (line_number, import_statement) tuples
    """
    if not dependencies:
        print("No dependencies found.")
        return

    print(f"Found {len(dependencies)} files with dependencies:")

    for file_path, refs in sorted(dependencies.items()):
        print(f"\n{file_path}:")
        for line_number, statement in sorted(refs):
            print(f"  Line {line_number}: {statement}")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python analyze_module_dependencies.py MODULE_NAME [DIRECTORY]")
        sys.exit(1)

    module_name = sys.argv[1]
    directory = sys.argv[2] if len(sys.argv) > 2 else "src"

    print(f"Analyzing dependencies on module: {module_name}")
    dependencies = analyze_module_dependencies(module_name, directory)
    print_dependencies(dependencies)

    # Also check tests directory if not already specified
    if directory != "tests" and directory.lower() != "tests":
        print("\nChecking tests directory...")
        test_dependencies = analyze_module_dependencies(module_name, "tests")
        print_dependencies(test_dependencies)


if __name__ == "__main__":
    main()
