from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_EMPTY_HTML_COMMENT_RE = re.compile(r"[ \t]*<!--\s*-->[ \t]*")
_TRAILING_HTML_COMMENT_OPEN_RE = re.compile(r"[ \t]*<!--\s*$")
_LEADING_HTML_COMMENT_CLOSE_RE = re.compile(r"^\s*-->\s*")
_HTML_COMMENT_BOUNDARY_RE = re.compile(
    rf"{_EMPTY_HTML_COMMENT_RE.pattern}|{_TRAILING_HTML_COMMENT_OPEN_RE.pattern}"
)


@dataclass(frozen=True, slots=True)
class ReasoningSummarySanitizerState:
    """Cross-delta state for hidden Codex reasoning-summary boundaries."""

    has_visible_text: bool = False
    previous_ended_with_newline: bool = False
    separator_pending: bool = False
    last_output_index: Any = None
    last_summary_index: Any = None


def collect_reasoning_lines(value: Any, depth: int = 0) -> list[str]:
    """Recursively collect textual fragments from nested reasoning payloads."""
    if value is None or depth > 50:
        return []

    if isinstance(value, str):
        return [value]

    if isinstance(value, int | float | bool):
        return [str(value)]

    if isinstance(value, list | tuple | set):
        sequence_values: list[str] = []
        for item in value:
            sequence_values.extend(collect_reasoning_lines(item, depth + 1))
        return sequence_values

    if isinstance(value, dict):
        collected_values: list[str] = []
        for key in (
            "thinking",
            "reasoning",
            "text",
            "value",
            "content",
            "message",
            "delta",
        ):
            if key in value:
                collected_values.extend(collect_reasoning_lines(value[key], depth + 1))
        return collected_values

    return [str(value)]


def coerce_reasoning_text(value: Any) -> str | None:
    """Flatten nested reasoning payloads into a normalized text snippet."""
    # IMPORTANT: Do NOT strip segments here. In streaming mode, segments are often
    # single tokens (spaces, newlines, or words with leading/trailing spaces).
    # Stripping them causes concatenation issues (e.g. "word word" -> "wordword").
    parts = collect_reasoning_lines(value)
    if not parts:
        return None

    # Filter out empty strings but keep whitespace-only strings (tokens)
    parts = [p for p in parts if p != ""]
    if not parts:
        return None

    # If we have a single part, return it as-is to preserve streaming tokens
    if len(parts) == 1:
        return parts[0]

    # For multiple parts, join them with newlines as they likely represent
    # different sources or blocks of reasoning.
    return "\n".join(parts)


def sanitize_reasoning_summary_stream_delta(
    text: str,
    state: ReasoningSummarySanitizerState | None = None,
    *,
    output_index: Any = None,
    summary_index: Any = None,
) -> tuple[str, ReasoningSummarySanitizerState]:
    """Hide markers and resolve separators between adjacent reasoning sections."""
    current = state or ReasoningSummarySanitizerState()
    has_visible_text = current.has_visible_text
    previous_ended_with_newline = current.previous_ended_with_newline
    summary_section_changed = (
        summary_index is not None
        and current.last_summary_index is not None
        and summary_index != current.last_summary_index
    ) or (
        output_index is not None
        and current.last_output_index is not None
        and output_index != current.last_output_index
    )
    separator_pending = current.separator_pending or (
        summary_section_changed and has_visible_text
    )
    output: list[str] = []

    text = _LEADING_HTML_COMMENT_CLOSE_RE.sub("", text)
    for index, part in enumerate(_HTML_COMMENT_BOUNDARY_RE.split(text)):
        if index > 0:
            separator_pending = separator_pending or has_visible_text
        if not part:
            continue
        if separator_pending:
            if (
                has_visible_text
                and not previous_ended_with_newline
                and not part.startswith(("\r", "\n"))
            ):
                output.append("\n")
            separator_pending = False
        output.append(part)
        has_visible_text = True
        previous_ended_with_newline = part.endswith(("\r", "\n"))

    return "".join(output), ReasoningSummarySanitizerState(
        has_visible_text=has_visible_text,
        previous_ended_with_newline=previous_ended_with_newline,
        separator_pending=separator_pending,
        last_output_index=(
            output_index if output_index is not None else current.last_output_index
        ),
        last_summary_index=(
            summary_index if summary_index is not None else current.last_summary_index
        ),
    )


def strip_empty_html_comment_markers(text: str) -> str:
    """Remove markers from one isolated reasoning-summary value."""
    sanitized, _ = sanitize_reasoning_summary_stream_delta(text)
    return sanitized


def safe_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes | bytearray):
        return value.decode("utf-8", "ignore")
    return str(value)
