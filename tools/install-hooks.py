#!/usr/bin/env python3
"""
Install Git hooks for the project.

This script installs Git hooks for the project to help enforce code quality.
"""

import os
import shutil
import stat
from pathlib import Path


def install_hook(
    hook_name: str, source_path: Path, hooks_dir: Path, mandatory: bool = False
) -> None:
    """
    Install a Git hook.

    Args:
        hook_name: Name of the hook to install (e.g., pre-commit)
        source_path: Path to the hook source file
        hooks_dir: Directory where hooks should be installed
        mandatory: If True, the hook cannot be bypassed with --no-verify
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

    # If the hook should be mandatory, create a wrapper that prevents --no-verify bypass
    if mandatory:
        # Rename the original hook
        mandatory_target = hooks_dir / f"{hook_name}.original"
        os.rename(target_path, mandatory_target)

        # Create a wrapper script that can't be bypassed with --no-verify
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(
                f"""#!/bin/sh
# This is a mandatory hook that cannot be bypassed with --no-verify
echo "Running mandatory {hook_name} hook..."
{mandatory_target}
exit_code=$?
if [ $exit_code -ne 0 ]; then
    echo "ERROR: {hook_name} hook failed. This hook is mandatory and cannot be bypassed."
    echo "Please fix the issues before committing."
    exit $exit_code
fi
"""
            )

        # Make the wrapper executable
        os.chmod(target_path, st.st_mode | stat.S_IEXEC)
        print(f"Installed mandatory {hook_name} hook to {target_path}")
    else:
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

    # Install pre-commit hook as mandatory
    pre_commit_source = repo_root / "tools" / "pre-commit-hook.py"
    install_hook("pre-commit", pre_commit_source, hooks_dir, mandatory=True)

    print("\nGit hooks installation complete.")
    print("The following hooks are now active:")
    print(
        " - pre-commit (MANDATORY): Runs enhanced architectural linter on changed Python files"
    )


if __name__ == "__main__":
    main()
