#!/usr/bin/env python3
"""
Pre-commit hook for enforcing architectural patterns.

This script can be used as a pre-commit hook to enforce architectural patterns
before allowing commits. It runs the architectural_linter.py tool on changed
Python files to ensure they follow the architectural guidelines.

Usage:
    1. Copy this file to .git/hooks/pre-commit
    2. Make it executable: chmod +x .git/hooks/pre-commit
    3. The hook will run automatically on each commit
"""

import os
import subprocess
import sys
from pathlib import Path


def get_changed_python_files() -> list[str]:
    """
    Get a list of changed Python files that are staged for commit.

    Returns:
        List of changed Python files
    """
    # Get the list of changed files that are staged for commit
    result = subprocess.run(
        ["git", "diff", "--name-only", "--cached"],
        check=True,
        capture_output=True,
        text=True,
    )
    changed_files = result.stdout.strip().split("\n")

    # Filter for only Python files
    return [f for f in changed_files if f.endswith(".py") and os.path.exists(f)]


def check_architectural_patterns(files: list[str]) -> bool:
    """
    Check architectural patterns in the given files.

    Args:
        files: List of files to check

    Returns:
        True if all checks pass, False otherwise
    """
    # Get the path to the enhanced architectural linter
    repo_root = Path(__file__).resolve().parents[1]
    linter_path = repo_root / "tools" / "architectural_linter_enhanced.py"

    # Fall back to the original linter if the enhanced one doesn't exist
    if not linter_path.exists():
        linter_path = repo_root / "tools" / "architectural_linter.py"

    # Verify the linter exists
    if not linter_path.exists():
        print(f"Error: Architectural linter not found at {linter_path}")
        return False

    # Find the Python interpreter to use
    venv_python = repo_root / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        python_path = venv_python
    else:
        python_path = "python3"

    # Check each file
    any_errors = False

    for file_path in files:
        # Skip files in /tests/ directory
        if "/tests/" in file_path or "\\tests\\" in file_path:
            continue

        # Skip migrations and auto-generated files
        if "migrations" in file_path or "generated" in file_path:
            continue

        print(f"Checking architectural patterns in: {file_path}")
        result = subprocess.run(
            [str(python_path), str(linter_path), file_path],
            capture_output=True,
            text=True,
        )

        # Check for errors
        if result.returncode != 0:
            print(f"Architectural violations found in {file_path}:")
            print(result.stdout)
            any_errors = True

    return not any_errors


def main() -> int:
    """
    Main entry point for the pre-commit hook.

    Returns:
        0 if successful, non-zero otherwise
    """
    changed_files = get_changed_python_files()

    if not changed_files:
        print("No Python files changed, skipping architectural checks.")
        return 0

    print(f"Checking architectural patterns in {len(changed_files)} files...")
    if check_architectural_patterns(changed_files):
        print("All architectural checks passed.")
        return 0
    else:
        print("\nERROR: Architectural violations found!")
        print("Please fix these issues before committing.")
        print(
            "Run tools/architectural_linter_enhanced.py on your files for more details."
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
