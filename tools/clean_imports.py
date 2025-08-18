#!/usr/bin/env python3
"""
Clean up imports referencing legacy modules.

This script scans Python files for imports of legacy modules and removes them.
"""

import os
import re
from pathlib import Path


def clean_imports(file_path: Path) -> bool:
    """
    Clean up imports referencing legacy modules in a file.

    Args:
        file_path: Path to the file to clean

    Returns:
        True if the file was modified, False otherwise
    """
    # Legacy import patterns to remove
    legacy_import_patterns = [
        r"from src\.proxy_logic import .*",
        r"from src\.proxy_logic_deprecated import .*",
        r"import src\.proxy_logic",
        r"import src\.proxy_logic_deprecated",
        r"from src\.core\.app\.legacy_state_compatibility import .*",
        r"import src\.core\.app\.legacy_state_compatibility",
        r"from src\.core\.adapters\.legacy_.*",
        r"import src\.core\.adapters\.legacy_.*",
    ]

    # Read the file content
    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    # Check if any legacy import pattern is found
    original_content = content
    for pattern in legacy_import_patterns:
        content = re.sub(pattern, "# Removed legacy import", content)

    # Write the file if it was modified
    if content != original_content:
        print(f"Cleaning imports in {file_path}")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True

    return False


def main():
    """Clean up imports in all Python files."""
    root_dir = Path(__file__).parent.parent
    modified_files = 0
    scanned_files = 0

    # Walk through all Python files
    for root, _, files in os.walk(root_dir):
        for file in files:
            if file.endswith(".py"):
                file_path = Path(root) / file
                scanned_files += 1
                if clean_imports(file_path):
                    modified_files += 1

    print(f"Scanned {scanned_files} files, modified {modified_files} files.")


if __name__ == "__main__":
    main()
