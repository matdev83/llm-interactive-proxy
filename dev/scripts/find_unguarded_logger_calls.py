#!/usr/bin/env python3
"""Find unguarded logger calls with f-strings or expensive operations."""

import os
import re
import sys


def check_file(filepath: str) -> list[tuple[int, str]]:
    """Check a file for unguarded logger calls."""
    with open(filepath, encoding="utf-8") as f:
        lines = f.readlines()

    unguarded = []
    for i, line in enumerate(lines):
        # Check for logger.debug/info/warning
        if re.search(r'logger\.(debug|info|warning)\(', line):
            # Check if it has expensive operations (f-string, .format, json.dumps, model_dump)
            has_expensive = (
                re.search(r'logger\.(debug|info|warning)\(f["\']', line)
                or ".format(" in line
                or "json.dumps(" in line
                or "model_dump(" in line
            )
            
            if has_expensive:
                # Check if previous lines have guard
                guarded = False
                for j in range(max(0, i - 5), i):
                    if "isEnabledFor" in lines[j]:
                        guarded = True
                        break
                if not guarded:
                    unguarded.append((i + 1, line.strip()))

    return unguarded


def main() -> None:
    """Main entry point."""
    found_any = False
    for root, dirs, files in os.walk("src"):
        # Skip dot/underscore directories
        dirs[:] = [d for d in dirs if not d.startswith(".") and not d.startswith("_")]

        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                unguarded = check_file(filepath)
                if unguarded:
                    found_any = True
                    print(f"{filepath}:")
                    for line_num, line in unguarded:
                        print(f"  {line_num}: {line}")

    if not found_any:
        print("No unguarded logger calls found.")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
