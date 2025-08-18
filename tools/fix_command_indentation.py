#!/usr/bin/env python3
"""
Fix indentation issues in command files.

This script fixes indentation issues in command files that have empty TYPE_CHECKING blocks.
"""

import re
from pathlib import Path


def fix_indentation(file_path: Path) -> bool:
    """
    Fix indentation issues in a file.

    Args:
        file_path: Path to the file to fix

    Returns:
        True if the file was modified, False otherwise
    """
    # Read the file content
    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    # Check if the file has the indentation issue
    pattern = r"if TYPE_CHECKING:[\r\n]+\s+# Removed legacy import"
    if not re.search(pattern, content):
        return False

    # Fix the indentation issue
    fixed_content = re.sub(
        pattern, "if TYPE_CHECKING:\n    pass  # No imports needed", content
    )

    # Write the file if it was modified
    if fixed_content != content:
        print(f"Fixing indentation in {file_path}")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(fixed_content)
        return True

    return False


def fix_proxy_state_references(file_path: Path) -> bool:
    """
    Fix ProxyState references in a file.

    Args:
        file_path: Path to the file to fix

    Returns:
        True if the file was modified, False otherwise
    """
    # Read the file content
    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    # Check if the file has ProxyState references
    pattern = r"def\s+\w+\([^)]*state:\s*ProxyState[^)]*\)"
    if not re.search(pattern, content):
        return False

    # Fix ProxyState references
    fixed_content = re.sub(
        pattern,
        lambda m: m.group(0).replace("ProxyState", "Any"),
        content,
    )

    # Write the file if it was modified
    if fixed_content != content:
        print(f"Fixing ProxyState references in {file_path}")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(fixed_content)
        return True

    return False


def main():
    """Fix indentation issues in all command files."""
    root_dir = Path(__file__).parent.parent
    commands_dir = root_dir / "src" / "commands"
    modified_files = 0
    scanned_files = 0

    # Walk through all Python files in the commands directory
    for file_path in commands_dir.glob("*.py"):
        scanned_files += 1
        if fix_indentation(file_path):
            modified_files += 1
        if fix_proxy_state_references(file_path):
            modified_files += 1

    print(f"Scanned {scanned_files} files, modified {modified_files} files.")


if __name__ == "__main__":
    main()
