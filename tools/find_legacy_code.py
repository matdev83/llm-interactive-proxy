#!/usr/bin/env python3
"""
Find legacy code in the codebase.
"""

import os
import sys


def find_legacy_code(directory: str, pattern: str) -> list[tuple[str, str, int]]:
    """Find files containing the pattern.
    
    Args:
        directory: Directory to search
        pattern: Pattern to search for
        
    Returns:
        List of (file_path, line, line_number) tuples
    """
    results = []
    for root, _, files in os.walk(directory):
        for file in files:
            if not file.endswith('.py'):
                continue
                
            file_path = os.path.join(root, file)
            try:
                with open(file_path, encoding='utf-8') as f:
                    for i, line in enumerate(f, 1):
                        if pattern.lower() in line.lower():
                            results.append((file_path, line.strip(), i))
            except Exception as e:
                print(f"Error reading {file_path}: {e}", file=sys.stderr)
                
    return results


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <directory> <pattern>")
        sys.exit(1)
        
    directory = sys.argv[1]
    pattern = sys.argv[2]
    
    results = find_legacy_code(directory, pattern)
    
    # Sort by file path
    results.sort(key=lambda x: x[0])
    
    # Print results
    for file_path, line, line_number in results:
        print(f"{file_path}:{line_number}: {line}")
    
    print(f"\nFound {len(results)} matches")


if __name__ == "__main__":
    main()
