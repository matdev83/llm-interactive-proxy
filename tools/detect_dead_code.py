#!/usr/bin/env python3
"""
Dead Code Detection Tool

This script uses the vulture library to detect potentially unused code in the project.
It provides options to filter results and exclude certain patterns.

Usage:
    python tools/detect_dead_code.py [--min-confidence=<n>] [--exclude=<pattern>]

Options:
    --min-confidence=<n>    Minimum confidence threshold (0-100) [default: 80]
    --exclude=<pattern>     Glob pattern to exclude from analysis
    --verbose               Show more detailed output
    --quiet                 Show only the file paths with dead code
    --json                  Output results in JSON format
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import vulture
except ImportError:
    print("Error: vulture package not found. Install with 'pip install vulture'")
    sys.exit(1)


class DeadCodeDetector:
    """Detects dead code in the project using vulture."""

    def __init__(
        self,
        min_confidence: int = 80,
        exclude_patterns: list[str] | None = None,
        verbose: bool = False,
        quiet: bool = False,
    ):
        """Initialize the detector.

        Args:
            min_confidence: Minimum confidence threshold (0-100)
            exclude_patterns: List of glob patterns to exclude
            verbose: Whether to show more detailed output
            quiet: Whether to show only the file paths
        """
        self.min_confidence = min_confidence
        self.exclude_patterns = exclude_patterns or []
        self.verbose = verbose
        self.quiet = quiet

        # Add default excludes for this project
        self.exclude_patterns.extend(
            [
                # Numba-related false positives
                "**/numba*",
                "**/*_numba*",
                # Test files
                "**/test_*.py",
                "**/conftest.py",
                # Build artifacts
                "**/build/**",
                "**/dist/**",
                "**/*.egg-info/**",
                # Virtual environment
                "**/.venv/**",
                "**/venv/**",
                # Documentation
                "**/docs/**",
                # Examples
                "**/examples/**",
            ]
        )

    def detect(self, paths: list[str]) -> list[dict]:
        """Run the detection on the given paths.

        Args:
            paths: List of paths to analyze

        Returns:
            List of dead code items found
        """
        v = vulture.Vulture(verbose=self.verbose)

        # Set minimum confidence
        v.confidence_default = self.min_confidence

        # Add paths to scan
        for path in paths:
            if os.path.isdir(path):
                v.scavenge([path])
            else:
                v.scavenge_file(path)

        # Filter results by confidence and exclude patterns
        results = []
        for item in v.get_unused_code():
            # Skip if confidence is too low
            if item.confidence < self.min_confidence:
                continue

            # Skip if path matches exclude pattern
            if self._is_excluded(item.filename):
                continue

            # Add to results
            results.append(
                {
                    "type": item.typ,
                    "name": item.name,
                    "filename": item.filename,
                    "line": item.first_lineno,
                    "size": item.size,
                    "confidence": item.confidence,
                }
            )

        return results

    def _is_excluded(self, path: str) -> bool:
        """Check if a path matches any exclude pattern.

        Args:
            path: Path to check

        Returns:
            True if path should be excluded
        """
        from fnmatch import fnmatch

        return any(fnmatch(path, pattern) for pattern in self.exclude_patterns)

    def print_results(self, results: list[dict]) -> None:
        """Print the results in a human-readable format.

        Args:
            results: List of dead code items
        """
        if not results:
            print("No dead code found!")
            return

        print(f"Found {len(results)} potentially dead code items:")

        # Group by file
        files: dict[str, list[dict]] = {}
        for item in results:
            filename = item["filename"]
            if filename not in files:
                files[filename] = []
            files[filename].append(item)

        # Print results by file
        for filename, items in files.items():
            if self.quiet:
                print(filename)
                continue

            print(f"\n{filename}:")
            for item in sorted(items, key=lambda x: x["line"]):
                print(
                    f"  Line {item['line']}: {item['type']} '{item['name']}' (confidence: {item['confidence']}%)"
                )

    def print_json(self, results: list[dict]) -> None:
        """Print the results in JSON format.

        Args:
            results: List of dead code items
        """
        print(json.dumps(results, indent=2))


def get_project_root() -> Path:
    """Get the project root directory.

    Returns:
        Path to the project root
    """
    # Start from the script directory and go up until we find pyproject.toml
    current = Path(__file__).parent

    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent

    # If we can't find it, use the script directory's parent
    return Path(__file__).parent.parent


def parse_args() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(description="Detect dead code in the project")
    parser.add_argument(
        "--min-confidence",
        type=int,
        default=80,
        help="Minimum confidence threshold (0-100)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Glob pattern to exclude from analysis",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show more detailed output",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Show only the file paths with dead code",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Paths to analyze (default: src)",
    )

    return parser.parse_args()


def main() -> None:
    """Run the script."""
    args = parse_args()

    # Get project root
    root = get_project_root()

    # Default to src directory if no paths provided
    paths = args.paths
    if not paths:
        paths = [str(root / "src")]

    # Create detector
    detector = DeadCodeDetector(
        min_confidence=args.min_confidence,
        exclude_patterns=args.exclude,
        verbose=args.verbose,
        quiet=args.quiet,
    )

    # Run detection
    results = detector.detect(paths)

    # Print results
    if args.json:
        detector.print_json(results)
    else:
        detector.print_results(results)

    # Exit with error code if dead code found
    sys.exit(1 if results else 0)


if __name__ == "__main__":
    main()
