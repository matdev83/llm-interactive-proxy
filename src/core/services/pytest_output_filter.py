"""Shared pytest output line filtering (legacy-compatible semantics)."""

from __future__ import annotations

import re

_PASSED_PATTERN = re.compile(r"\bPASSED\b", re.IGNORECASE)
_TIMING_SEGMENT_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?s\s+(setup|call|teardown)\b|\bs\s+(setup|call|teardown)\b",
    re.IGNORECASE,
)
_WHITESPACE_PATTERN = re.compile(r"\s{2,}")

_COLLECTED_ITEMS_RE = re.compile(r"collected\s+\d+\s+items?\b", re.IGNORECASE)


def looks_like_pytest_command(
    command_signature: str | None, command_prefix: str | None
) -> bool:
    """True when resolved command identity clearly targets pytest."""
    sig = (command_signature or "").lower()
    if sig == "pytest":
        return True
    prefix = (command_prefix or "").lower()
    return "pytest" in prefix or "py.test" in prefix


def looks_like_pytest_output(text: str) -> bool:
    """Heuristic: output resembles pytest console format (matches legacy gating)."""
    if not text:
        return False
    lower = text.lower()
    if "test session starts" in lower or "short test summary info" in lower:
        return True
    return bool(_COLLECTED_ITEMS_RE.search(text)) or (
        "pytest-" in lower and re.search(r"pytest-\d+\.\d+", lower) is not None
    )


def filter_pytest_output(output: str) -> str:
    """Filter pytest output to remove PASSED lines and inline timing (legacy semantics).

    Matches ``AgentResponseFormatter._filter_pytest_output`` behavior: preserve the
    last line unconditionally; split lines without stripping the full payload first.
    """
    if not output:
        return output

    lines = output.split("\n")
    if not lines:
        return output

    last_line = lines[-1] if lines else ""
    lines_to_process = lines[:-1] if len(lines) > 1 else []

    filtered_lines: list[str] = []
    for line in lines_to_process:
        if _PASSED_PATTERN.search(line):
            continue
        trimmed = _TIMING_SEGMENT_PATTERN.sub("", line)
        trimmed = _WHITESPACE_PATTERN.sub(" ", trimmed).strip()
        if trimmed:
            filtered_lines.append(trimmed)

    filtered_lines.append(last_line)
    return "\n".join(filtered_lines)
