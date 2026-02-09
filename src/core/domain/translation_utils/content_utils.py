from __future__ import annotations

from typing import Any


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



def safe_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes | bytearray):
        return value.decode("utf-8", "ignore")
    return str(value)
