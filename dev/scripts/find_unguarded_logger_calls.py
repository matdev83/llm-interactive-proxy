"""Script to find unguarded logger calls in the codebase.

Scans Python files for logger.debug(), logger.info(), logger.warning() calls
that are not guarded by isEnabledFor checks.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple


class UnguardedCall(NamedTuple):
    """Represents an unguarded logger call."""

    file_path: Path
    line_number: int
    call_type: str  # 'debug', 'info', 'warning'
    code_snippet: str


def find_unguarded_calls(file_path: Path) -> list[UnguardedCall]:
    """Find unguarded logger calls in a Python file.

    Args:
        file_path: Path to the Python file to scan

    Returns:
        List of unguarded logger calls found
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return []

    lines = content.splitlines()
    unguarded: list[UnguardedCall] = []

    # Pattern to match logger.debug/info/warning calls
    logger_pattern = re.compile(
        r"logger\.(debug|info|warning)\s*\(",
        re.IGNORECASE,
    )

    # Pattern to check for isEnabledFor guard
    guard_pattern = re.compile(
        r"if\s+.*logger\.isEnabledFor\s*\(",
        re.IGNORECASE,
    )

    for idx, line in enumerate(lines):
        # Check if this line contains a logger call
        match = logger_pattern.search(line)
        if not match:
            continue

        call_type = match.group(1).lower()
        line_num = idx + 1

        # Check if there's a guard within 5 lines before
        # Look at lines before (up to 5 lines back)
        guard_found = False
        check_start = max(0, idx - 5)
        context_lines = lines[check_start : idx + 1]
        context_text = "\n".join(context_lines)

        # Check for guard pattern
        if guard_pattern.search(context_text):
            # Verify the guard is actually guarding this call
            # by checking if there's an if statement that's not closed
            # This is a simple heuristic - we'll be conservative
            guard_found = True

        # Also check if this is inside an existing guard block
        # by looking for indentation patterns
        if not guard_found:
            # Check if previous non-empty line is an if statement with isEnabledFor
            for prev_idx in range(idx - 1, max(-1, idx - 6), -1):
                if prev_idx < 0:
                    break
                prev_line = lines[prev_idx].strip()
                if not prev_line:
                    continue
                if guard_pattern.search(prev_line):
                    # Check indentation - if prev line has less or equal indentation
                    # and current line is more indented, it might be guarded
                    prev_indent = len(lines[prev_idx]) - len(lines[prev_idx].lstrip())
                    curr_indent = len(line) - len(line.lstrip())
                    if curr_indent > prev_indent:
                        guard_found = True
                    break
                # If we hit a line with same or less indentation that's not empty,
                # stop looking
                if prev_line and not prev_line.startswith("#"):
                    prev_indent = len(lines[prev_idx]) - len(lines[prev_idx].lstrip())
                    curr_indent = len(line) - len(line.lstrip())
                    if prev_indent <= curr_indent:
                        break

        if not guard_found:
            # Get code snippet (3 lines before and after)
            snippet_start = max(0, idx - 3)
            snippet_end = min(len(lines), idx + 4)
            snippet = "\n".join(
                f"{i+1:4d}: {lines[i]}" for i in range(snippet_start, snippet_end)
            )
            unguarded.append(
                UnguardedCall(
                    file_path=file_path,
                    line_number=line_num,
                    call_type=call_type,
                    code_snippet=snippet,
                )
            )

    return unguarded


def main() -> None:
    """Main entry point."""
    # Find all Python files in src/ and tests/
    src_dir = Path("src")
    tests_dir = Path("tests")

    all_files: list[Path] = []
    if src_dir.exists():
        all_files.extend(src_dir.rglob("*.py"))
    if tests_dir.exists():
        all_files.extend(tests_dir.rglob("*.py"))

    # Filter out __pycache__ and other excluded directories
    all_files = [
        f
        for f in all_files
        if "__pycache__" not in str(f)
        and ".venv" not in str(f)
        and "node_modules" not in str(f)
    ]

    print(f"Scanning {len(all_files)} Python files...")

    all_unguarded: list[UnguardedCall] = []
    for file_path in sorted(all_files):
        unguarded = find_unguarded_calls(file_path)
        all_unguarded.extend(unguarded)

    # Group by file
    by_file: dict[Path, list[UnguardedCall]] = {}
    for call in all_unguarded:
        if call.file_path not in by_file:
            by_file[call.file_path] = []
        by_file[call.file_path].append(call)

    # Print summary
    print(f"\nFound {len(all_unguarded)} unguarded logger calls in {len(by_file)} files\n")

    # Print details
    for file_path in sorted(by_file.keys()):
        calls = by_file[file_path]
        print(f"{file_path} ({len(calls)} calls):")
        for call in calls:
            print(f"  Line {call.line_number}: logger.{call.call_type}()")
        print()

    # Print summary by type
    debug_count = sum(1 for c in all_unguarded if c.call_type == "debug")
    info_count = sum(1 for c in all_unguarded if c.call_type == "info")
    warning_count = sum(1 for c in all_unguarded if c.call_type == "warning")

    print("\nSummary by type:")
    print(f"  debug: {debug_count}")
    print(f"  info: {info_count}")
    print(f"  warning: {warning_count}")


if __name__ == "__main__":
    main()

