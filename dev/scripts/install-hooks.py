#!/usr/bin/env python3
# ruff: noqa: N999
"""
Install Git hooks for the project.

This script installs Git hooks for the project to help enforce code quality.
"""

import os
import shutil
import stat
import subprocess
from datetime import datetime
from pathlib import Path


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _backup_existing(path: Path) -> None:
    if not path.exists():
        return
    backup = path.with_name(f"{path.name}.bak.{_timestamp()}")
    os.rename(path, backup)
    print(f"Backed up existing hook: {path} -> {backup}")


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

    # If the hook should be mandatory, create a wrapper that prevents --no-verify bypass
    if mandatory:
        mandatory_target = hooks_dir / f"{hook_name}.original"

        # Make repeated installs safe: rotate any existing hook files out of the way.
        _backup_existing(mandatory_target)
        _backup_existing(target_path)

        # Install the real hook script as {hook}.original.
        shutil.copy2(source_path, mandatory_target)
        st = os.stat(mandatory_target)
        os.chmod(mandatory_target, st.st_mode | stat.S_IEXEC)

        # Create a wrapper script that can't be bypassed with --no-verify.
        with open(target_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(
                f"""#!/bin/sh
# Mandatory {hook_name} hook; cannot be bypassed with --no-verify
echo "Running mandatory {hook_name} hook..."

# Resolve repo root and hook paths in a portable way
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$REPO_ROOT" ]; then
  echo "ERROR: Unable to determine repo root"
  exit 1
fi

ORIGINAL_HOOK="$REPO_ROOT/.git/hooks/{hook_name}.original"
PYTHON_BIN="$REPO_ROOT/.venv/Scripts/python.exe"

# Prefer venv Python if present; otherwise, try to execute the hook directly
if [ -x "$PYTHON_BIN" ]; then
  HOOK_TO_RUN="$ORIGINAL_HOOK"

  case "$PYTHON_BIN" in
    *.exe)
      if command -v wslpath >/dev/null 2>&1; then
        WINDOWS_PATH=$(wslpath -w "$ORIGINAL_HOOK" 2>/dev/null) || WINDOWS_PATH=""
        if [ -n "$WINDOWS_PATH" ]; then
          HOOK_TO_RUN="$WINDOWS_PATH"
        fi
      fi
      ;;
  esac

  "$PYTHON_BIN" "$HOOK_TO_RUN"
else
  "$ORIGINAL_HOOK"
fi

exit_code=$?
if [ $exit_code -ne 0 ]; then
  echo "ERROR: {hook_name} hook failed. This hook is mandatory and cannot be bypassed."
  echo "Please fix the issues before committing."
  exit $exit_code
fi
"""
            )

        st = os.stat(target_path)
        os.chmod(target_path, st.st_mode | stat.S_IEXEC)
        print(f"Installed mandatory {hook_name} hook to {target_path}")
    else:
        _backup_existing(target_path)
        shutil.copy2(source_path, target_path)
        st = os.stat(target_path)
        os.chmod(target_path, st.st_mode | stat.S_IEXEC)
        print(f"Installed {hook_name} hook to {target_path}")


def main() -> None:
    """Main entry point."""
    # Resolve repository root via git to avoid path assumptions
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        print("Error: Unable to determine repository root (git rev-parse failed).")
        return

    repo_root_str = result.stdout.strip()
    if not repo_root_str:
        print("Error: Unable to determine repository root.")
        return

    repo_root = Path(repo_root_str)

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
    pre_commit_source = repo_root / "dev" / "scripts" / "pre-commit-hook.py"
    install_hook("pre-commit", pre_commit_source, hooks_dir, mandatory=True)

    print("\nGit hooks installation complete.")
    print("The following hooks are now active:")
    print(
        " - pre-commit (MANDATORY): Runs secret scan (incl. ZAI pattern) and architectural linter on staged files"
    )


if __name__ == "__main__":
    main()
