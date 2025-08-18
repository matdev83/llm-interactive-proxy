#!/usr/bin/env python3
"""
Script to find functions and methods with missing type annotations in our project.
"""

import os
import re
from typing import List, Tuple


def find_functions_with_missing_types(root_dir: str) -> List[Tuple[str, int, str]]:
    """Find all functions and methods with missing parameter or return type annotations."""
    files_with_issues = []
    
    # Only look in src and tests directories
    target_dirs = ['src', 'tests']
    
    for target_dir in target_dirs:
        full_target_dir = os.path.join(root_dir, target_dir)
        if not os.path.exists(full_target_dir):
            continue
            
        for root, dirs, files in os.walk(full_target_dir):
            # Skip .git, __pycache__, and other directories
            dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', '.venv', '.mypy_cache', '.pytest_cache', '.ruff_cache']]
            
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            lines = content.split('\n')
                            
                            for i, line in enumerate(lines):
                                # Look for function definitions
                                if line.strip().startswith('def ') and ':' in line:
                                    # Get the full function signature (may span multiple lines)
                                    func_lines = [line.strip()]
                                    j = i + 1
                                    while j < len(lines) and lines[j].strip().startswith(('    ', '\t')) and ':' not in lines[j] and '->' not in lines[j]:
                                        func_lines.append(lines[j].strip())
                                        j += 1
                                    
                                    full_signature = ' '.join(func_lines)
                                    
                                    # Check if it's missing parameter types or return type
                                    has_issues = False
                                    
                                    # Check if it's missing return type annotation (and not a constructor)
                                    if '->' not in full_signature and '__init__' not in full_signature:
                                        has_issues = True
                                    
                                    # Check if it has untyped parameters
                                    # Extract parameters from the signature
                                    param_match = re.search(r'def\s+\w+\s*\(([^)]*)\)', full_signature)
                                    if param_match:
                                        params = param_match.group(1)
                                        # Check if there are parameters without type annotations
                                        # (excluding self, cls, and parameters that already have type annotations)
                                        if params and 'self' not in params and 'cls' not in params:
                                            # Simple check for parameters without type annotations
                                            # This is a basic check and might need refinement
                                            param_parts = [p.strip() for p in params.split(',')]
                                            for param in param_parts:
                                                if param and ':' not in param and '=' not in param and param != 'self' and param != 'cls':
                                                    # Check if it's a simple parameter without type annotation
                                                    if not re.search(r'\w+\s*:', param):
                                                        has_issues = True
                                                        break
                                    
                                    if has_issues:
                                        # Only add if it's in our project directories
                                        if 'src/' in file_path or 'tests/' in file_path:
                                            files_with_issues.append((file_path, i + 1, full_signature))
                    except Exception as e:
                        print("Error reading {}: {}".format(file_path, e))
    
    return files_with_issues


def main():
    """Main function."""
    root_dir = "."
    issues = find_functions_with_missing_types(root_dir)
    
    if issues:
        print("Functions and methods with missing type annotations:")
        for file_path, line_num, line in issues:
            print("{}:{}: {}".format(file_path, line_num, line))
    else:
        print("All functions and methods in our project have complete type annotations!")


if __name__ == "__main__":
    main()