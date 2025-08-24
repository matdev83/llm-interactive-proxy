#!/usr/bin/env python3
"""
Script to update imports from src.main to src.core.app.application_factory.

This script updates all imports from src.main to src.core.app.application_factory
in the tests directory.
"""

import os
import re
from pathlib import Path


def update_imports_in_file(file_path: Path) -> bool:
    """Update imports in a single file.

    Args:
        file_path: Path to the file to update

    Returns:
        True if the file was modified, False otherwise
    """
    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    # Replace imports
    new_content = re.sub(
        r"from src\.main import build_app",
        "from src.core.app.application_factory import build_app",
        content,
    )

    # Replace other imports from src.main
    new_content = re.sub(
        r"from src\.main import (\w+)",
        r"# TODO: Import \1 from the appropriate module",
        new_content,
    )

    # Check if the file was modified
    if new_content != content:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True

    return False


def update_imports_in_directory(directory: Path) -> int:
    """Update imports in all Python files in a directory.

    Args:
        directory: Path to the directory to update

    Returns:
        Number of files modified
    """
    modified_count = 0

    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                file_path = Path(root) / file
                if update_imports_in_file(file_path):
                    modified_count += 1
                    print(f"Updated imports in {file_path}")

    return modified_count


def main() -> None:
    """Main entry point."""
    tests_dir = Path("tests")

    if not tests_dir.exists():
        print(f"Directory {tests_dir} does not exist")
        return

    modified_count = update_imports_in_directory(tests_dir)
    print(f"Updated imports in {modified_count} files")


if __name__ == "__main__":
    main()
