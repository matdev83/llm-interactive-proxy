from __future__ import annotations

from typing import Any


def get_first_delta(content_copy: dict[str, Any]) -> dict[str, Any] | None:
    """Get the first choice delta dict, or None."""
    choices = content_copy.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return None
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return None
    delta = first_choice.get("delta", {})
    return delta if isinstance(delta, dict) else None
