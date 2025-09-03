#!/usr/bin/env python3
"""
Install Git hooks for the project.

This script installs Git hooks for the project to help enforce code quality.
"""

import os
import shutil
import stat
from pathlib import Path


def install_hook(hook_name: str, source_path: Path, hooks_dir: Path) -> None:
    """
    Install a Git hook.

    Args:
        hook_name: Name of the hook to install (e.g., pre-commit)
        source_path: Path to the hook source file
        hooks_dir: Directory where hooks should be installed
    """
    if not source_path.exists():
        print(f"Error: Hook source file not found: {source_path}")
        return

    target_path = hooks_dir / hook_name

    # Copy the hook file
    shutil.copy2(source_path, target_path)

    # Make the hook executable
    st = os.stat(target_path)
    os.chmod(target_path, st.st_mode | stat.S_IEXEC)

    print(f"Installed {hook_name} hook to {target_path}")


def main() -> None:
    """Main entry point."""
    # Get repository root
    repo_root = Path(__file__).resolve().parents[1]

    # Check if .git directory exists
    git_dir = repo_root / ".git"
    if not git_dir.exists() or not git_dir.is_dir():
        print(f"Error: .git directory not found at {git_dir}")
        print("This script must be run from the repository root directory.")
        return

    # Get hooks directory
    hooks_dir = git_dir / "hooks"
    if not hooks_dir.exists():
        hooks_dir.mkdir()
        print(f"Created hooks directory: {hooks_dir}")

    # Install pre-commit hook
    pre_commit_source = repo_root / "tools" / "pre-commit-hook.py"
    install_hook("pre-commit", pre_commit_source, hooks_dir)

    print("\nGit hooks installation complete.")
    print("The following hooks are now active:")
    print(" - pre-commit: Runs architectural linter on changed Python files")


if __name__ == "__main__":
    main()
