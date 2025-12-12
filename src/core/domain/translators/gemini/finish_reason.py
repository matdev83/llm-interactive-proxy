from __future__ import annotations


def map_gemini_finish_reason(finish_reason: str | None) -> str | None:
    """Map Gemini finish reasons to canonical values."""
    if finish_reason is None:
        return None

    normalized = str(finish_reason).lower()
    mapping = {
        "stop": "stop",
        "max_tokens": "length",
        "safety": "content_filter",
        "tool_calls": "tool_calls",
    }
    return mapping.get(normalized, "stop")
