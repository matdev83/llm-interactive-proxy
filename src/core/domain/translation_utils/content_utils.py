from __future__ import annotations

from typing import Any


def _collect_reasoning_lines(value: Any, depth: int = 0) -> list[str]:
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
            sequence_values.extend(_collect_reasoning_lines(item, depth + 1))
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
                collected_values.extend(_collect_reasoning_lines(value[key], depth + 1))
        return collected_values

    return [str(value)]


def _coerce_reasoning_text(value: Any) -> str | None:
    """Flatten nested reasoning payloads into a normalized text snippet."""
    parts = [
        segment.strip()
        for segment in _collect_reasoning_lines(value)
        if isinstance(segment, str) and segment.strip()
    ]
    if not parts:
        return None
    return "\n".join(parts)


def _safe_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes | bytearray):
        return value.decode("utf-8", "ignore")
    return str(value)
