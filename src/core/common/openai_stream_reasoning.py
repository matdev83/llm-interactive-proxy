"""Helpers for detecting reasoning in OpenAI-shaped streaming payloads."""

from __future__ import annotations

from typing import Any


def openai_dict_has_reasoning_output(payload: dict[str, Any]) -> bool:
    """Return True when an OpenAI-shaped payload carries non-empty reasoning text.

    Checks delta/message fields used across providers (reasoning_content, reasoning,
    thinking, thought, reasoning_summary).
    """
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return False

    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta") or choice.get("message")
        if not isinstance(delta, dict):
            continue

        reasoning_val = (
            delta.get("reasoning_content")
            or delta.get("reasoning")
            or delta.get("thinking")
            or delta.get("thought")
            or delta.get("reasoning_summary")
        )
        if isinstance(reasoning_val, str) and reasoning_val.strip():
            return True

    return False
