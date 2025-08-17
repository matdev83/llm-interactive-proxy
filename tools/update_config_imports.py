"""
Script to update imports from src.core.config_adapter to src.core.config.

This script updates all imports from src.core.config_adapter to the appropriate
direct imports from src.core.config modules.
"""

import os
import re
from pathlib import Path

# Define the replacements
REPLACEMENTS = [
    # AppConfig
    (
        r"from src\.core\.config_adapter import (.*?)AppConfig(.*?)",
        r"from src.core.config.app_config import \1AppConfig\2",
    ),
    # _load_config
    (
        r"from src\.core\.config_adapter import (.*?)_load_config(.*?)",
        r"from src.core.config.config_loader import \1_load_config\2",
    ),
    # load_config
    (
        r"from src\.core\.config_adapter import (.*?)load_config(.*?)",
        r"from src.core.config.app_config import \1load_config\2",
    ),
    # _collect_api_keys
    (
        r"from src\.core\.config_adapter import (.*?)_collect_api_keys(.*?)",
        r"from src.core.config.config_loader import \1_collect_api_keys\2",
    ),
    # _keys_for
    (
        r"from src\.core\.config_adapter import (.*?)_keys_for(.*?)",
        r"from src.core.config.config_loader import \1_keys_for\2",
    ),
    # get_openrouter_headers
    (
        r"from src\.core\.config_adapter import (.*?)get_openrouter_headers(.*?)",
        r"from src.core.config.config_loader import \1get_openrouter_headers\2",
    ),
    # logger
    (
        r"from src\.core\.config_adapter import (.*?)logger(.*?)",
        r"from src.core.config.config_loader import \1logger\2",
    ),
]


def update_imports(file_path: Path) -> bool:
    """Update imports in a file.
    
    Args:
        file_path: The path to the file to update
        
    Returns:
        True if the file was modified, False otherwise
    """
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    original_content = content
    
    # Apply all replacements
    for pattern, replacement in REPLACEMENTS:
        content = re.sub(pattern, replacement, content)
        
    # Check if the file was modified
    if content != original_content:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
        
    return False


def main():
    """Main entry point."""
    # Get the project root
    project_root = Path(__file__).resolve().parent.parent
    
    # Find all Python files
    python_files = list(project_root.glob("**/*.py"))
    
    # Update imports in all files
    modified_files = []
    for file_path in python_files:
        if update_imports(file_path):
            modified_files.append(file_path)
            print(f"Updated imports in {file_path}")
            
    # Print summary
    print(f"\nScanned {len(python_files)} files, modified {len(modified_files)} files.")


if __name__ == "__main__":
    main()
