#!/usr/bin/env python3
"""
Identify deprecated methods and compatibility layers.

This script searches the codebase for deprecated methods,
compatibility wrappers, and legacy fallbacks that can be removed
once test migration to proper DI is complete.
"""

import os
import re
from pathlib import Path

# Patterns to identify deprecated methods and legacy code
PATTERNS = {
    "deprecated_comment": re.compile(r"#\s*.*\bdeprecated\b", re.IGNORECASE),
    "deprecated_docstring": re.compile(
        r'""".*\bdeprecated\b.*"""', re.IGNORECASE | re.DOTALL
    ),
    "legacy_marker": re.compile(r"#\s*.*\blegacy\b", re.IGNORECASE),
    "to_be_removed": re.compile(r"#\s*.*\b(to be|will be) removed\b", re.IGNORECASE),
    "compatibility_wrapper": re.compile(
        r"#\s*.*\bcompatibility wrapper\b", re.IGNORECASE
    ),
    "backwards_compat": re.compile(r"#\s*.*\bbackwards? compat", re.IGNORECASE),
    "fallback_pattern": re.compile(r"#\s*.*\bfallback\b.*\blegacy\b", re.IGNORECASE),
}


class DeprecationFinder:
    """Find deprecated methods and compatibility layers."""

    def __init__(self, root_dir: Path, ignore_dirs: set[str] | None = None):
        """
        Initialize the deprecation finder.

        Args:
            root_dir: Root directory to search
            ignore_dirs: Directories to ignore
        """
        self.root_dir = root_dir
        self.ignore_dirs = ignore_dirs or {
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            "build",
            "dist",
        }
        self.results: dict[str, list[tuple[int, str, str]]] = {}

    def should_ignore(self, path: Path) -> bool:
        """
        Check if a path should be ignored.

        Args:
            path: Path to check

        Returns:
            True if path should be ignored
        """
        return any(ignore_dir in path.parts for ignore_dir in self.ignore_dirs)

    def scan_file(self, file_path: Path) -> list[tuple[int, str, str]]:
        """
        Scan a file for deprecated methods and compatibility layers.

        Args:
            file_path: Path to file

        Returns:
            List of (line_number, matched_text, pattern_name) tuples
        """
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            matches = []
            lines = content.split("\n")

            # Check for patterns in each line
            for i, line in enumerate(lines, 1):
                for pattern_name, pattern in PATTERNS.items():
                    if pattern.search(line):
                        matches.append((i, line.strip(), pattern_name))

            # Check for patterns that might span multiple lines (e.g., docstrings)
            for pattern_name, pattern in PATTERNS.items():
                for match in pattern.finditer(content):
                    matched_text = match.group(0)
                    # Calculate line number based on content up to the match
                    line_number = content[: match.start()].count("\n") + 1
                    # Only add if not already captured in the line-by-line scan
                    if not any(m[0] == line_number for m in matches):
                        matches.append(
                            (line_number, matched_text.strip(), pattern_name)
                        )

            return matches
        except Exception as e:
            print(f"Error scanning {file_path}: {e}")
            return []

    def scan_directory(self) -> None:
        """Scan the root directory for deprecated methods."""
        for root, dirs, files in os.walk(self.root_dir):
            # Modify dirs in-place to skip ignored directories
            dirs[:] = [d for d in dirs if not self.should_ignore(Path(root) / d)]

            for file in files:
                if not file.endswith(".py"):
                    continue

                file_path = Path(root) / file
                matches = self.scan_file(file_path)

                if matches:
                    rel_path = file_path.relative_to(self.root_dir)
                    self.results[str(rel_path)] = matches

    def get_results(self) -> dict[str, list[tuple[int, str, str]]]:
        """Get the scan results."""
        return self.results

    def print_results(self) -> None:
        """Print the scan results."""
        total_matches = sum(len(matches) for matches in self.results.values())
        print(
            f"\nFound {total_matches} potential deprecated methods and compatibility layers in {len(self.results)} files:"
        )

        for file_path, matches in sorted(self.results.items()):
            print(f"\n{file_path}:")
            for line_number, text, pattern_name in sorted(matches, key=lambda x: x[0]):
                print(f"  Line {line_number} [{pattern_name}]: {text}")


def main() -> None:
    """Main entry point."""
    root_dir = Path(__file__).resolve().parents[1]
    src_dir = root_dir / "src"

    if not src_dir.exists():
        print(f"Error: Source directory not found at {src_dir}")
        return

    print(f"Scanning {src_dir} for deprecated methods and compatibility layers...")

    finder = DeprecationFinder(src_dir)
    finder.scan_directory()
    finder.print_results()

    print(
        "\nNote: These results indicate potential areas to clean up after test migration."
    )
    print(
        "Review each case carefully before removing, as some may still be needed for compatibility."
    )


if __name__ == "__main__":
    main()
