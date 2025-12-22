"""Script to automatically guard unguarded logger calls.

This script reads the unguarded logger calls report and applies guards
to all unguarded logger.debug(), logger.info(), and logger.warning() calls.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple


class LoggerCall(NamedTuple):
    """Represents a logger call location."""

    file_path: Path
    line_number: int
    call_type: str  # 'debug', 'info', 'warning'
    indentation: str


def find_unguarded_calls_in_file(file_path: Path) -> list[LoggerCall]:
    """Find unguarded logger calls in a file.

    Args:
        file_path: Path to Python file

    Returns:
        List of unguarded logger calls
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return []

    lines = content.splitlines()
    unguarded: list[LoggerCall] = []

    # Pattern to match logger.debug/info/warning calls
    logger_pattern = re.compile(
        r"^(\s*)logger\.(debug|info|warning)\s*\(",
        re.IGNORECASE,
    )

    # Pattern to check for isEnabledFor guard
    guard_pattern = re.compile(
        r"if\s+.*logger\.isEnabledFor\s*\(",
        re.IGNORECASE,
    )

    for idx, line in enumerate(lines):
        match = logger_pattern.match(line)
        if not match:
            continue

        indentation = match.group(1)
        call_type = match.group(2).lower()
        line_num = idx + 1

        # Check if there's a guard within 5 lines before
        guard_found = False
        check_start = max(0, idx - 5)
        context_lines = lines[check_start : idx + 1]
        context_text = "\n".join(context_lines)

        if guard_pattern.search(context_text):
            # Verify the guard is actually guarding this call
            # by checking indentation
            for prev_idx in range(idx - 1, max(-1, idx - 6), -1):
                if prev_idx < 0:
                    break
                prev_line = lines[prev_idx].strip()
                if not prev_line:
                    continue
                if guard_pattern.search(prev_line):
                    prev_indent = len(lines[prev_idx]) - len(lines[prev_idx].lstrip())
                    curr_indent = len(line) - len(line.lstrip())
                    if curr_indent > prev_indent:
                        guard_found = True
                    break
                if prev_line and not prev_line.startswith("#"):
                    prev_indent = len(lines[prev_idx]) - len(lines[prev_idx].lstrip())
                    curr_indent = len(line) - len(line.lstrip())
                    if prev_indent <= curr_indent:
                        break

        if not guard_found:
            unguarded.append(
                LoggerCall(
                    file_path=file_path,
                    line_number=line_num,
                    call_type=call_type,
                    indentation=indentation,
                )
            )

    return unguarded


def guard_logger_call(
    content: str, call: LoggerCall, level_map: dict[str, str]
) -> str:
    """Add guard to a logger call.

    Args:
        content: File content
        call: Logger call to guard
        level_map: Map from call_type to logging level constant

    Returns:
        Modified content with guard added
    """
    lines = content.splitlines()
    line_idx = call.line_number - 1

    if line_idx >= len(lines):
        return content

    original_line = lines[line_idx]
    level = level_map[call.call_type]

    # Check if this is a multi-line call
    # Count opening and closing parentheses
    open_parens = original_line.count("(") - original_line.count(")")
    is_multiline = open_parens > 0

    if is_multiline:
        # Find the end of the call
        end_idx = line_idx
        paren_count = open_parens
        while end_idx < len(lines) - 1 and paren_count > 0:
            end_idx += 1
            paren_count += lines[end_idx].count("(") - lines[end_idx].count(")")

        # Insert guard before the call
        guard_line = f"{call.indentation}if logger.isEnabledFor(logging.{level}):"
        lines.insert(line_idx, guard_line)

        # Increase indentation of the logger call block
        for i in range(line_idx + 1, end_idx + 2):
            if i < len(lines):
                lines[i] = "    " + lines[i]

    else:
        # Single line call
        guard_line = f"{call.indentation}if logger.isEnabledFor(logging.{level}):"
        lines.insert(line_idx, guard_line)
        # Indent the logger call
        lines[line_idx + 1] = "    " + lines[line_idx + 1]

    return "\n".join(lines)


def main() -> None:
    """Main entry point - demonstrates usage."""
    print("This script provides utilities for guarding logger calls.")
    print("Use find_unguarded_calls_in_file() to find calls.")
    print("Use guard_logger_call() to add guards.")


if __name__ == "__main__":
    main()

