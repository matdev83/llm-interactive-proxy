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
    # Get the path to the architectural linter
    repo_root = Path(__file__).resolve().parents[1]
    linter_path = repo_root / "scripts" / "architectural_linter.py"

    # Verify the linter exists
    if not linter_path.exists():
        print(f"Error: Architectural linter not found at {linter_path}")
        return False

    # Find the Python interpreter to use
    venv_python = repo_root / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        python_path = venv_python
    else:
        python_path = Path("python3")

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


def run_secret_scan() -> bool:
    """Run pre-commit API key check to prevent secret leaks.

    Returns True if no secrets are detected; False otherwise.
    """
    repo_root = Path(__file__).resolve().parents[1]
    checker_path = repo_root / "scripts" / "pre_commit_api_key_check.py"

    if not checker_path.exists():
        # If checker is missing, do not block commits
        print(f"Warning: Secret checker not found at {checker_path}. Skipping.")
        return True

    # Prefer project venv interpreter
    venv_python = repo_root / ".venv" / "Scripts" / "python.exe"
    python_path = venv_python if venv_python.exists() else Path(sys.executable)

    print("Running secret scan on staged files...")
    result = subprocess.run(
        [str(python_path), str(checker_path)], capture_output=True, text=True
    )
    if result.returncode != 0:
        # Surface the tool's output for the user
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return False

    # Optional verbosity
    if result.stdout.strip():
        print(result.stdout.strip())
    return True


def main() -> int:
    """
    Main entry point for the pre-commit hook.

    Returns:
        0 if successful, non-zero otherwise
    """
    # 1) Run secret scanning first to prevent leaks regardless of file type
    if not run_secret_scan():
        print("\nERROR: Secret scan failed; potential API keys detected.")
        print("Please remove sensitive values from staged files before committing.")
        return 1

    # 2) Architectural checks for changed Python files
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
        print("Run scripts/architectural_linter.py on your files for more details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
