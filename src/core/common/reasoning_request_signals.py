"""Derive whether an inbound chat request asks for reasoning/thinking output."""

from __future__ import annotations

from typing import Any


def chat_request_indicates_reasoning_output(request: Any) -> bool:
    """Return True when the client request enables reasoning or extended thinking.

    Used to align empty-stream recovery with clients that expect reasoning deltas
    on the wire (e.g. OpenCode ``thinking: {type: enabled}`` in ``extra_body``).
    """
    if request is None:
        return False

    effort = getattr(request, "reasoning_effort", None)
    if isinstance(effort, str) and effort.strip():
        return True

    reasoning = getattr(request, "reasoning", None)
    if isinstance(reasoning, dict) and reasoning:
        return True

    if getattr(request, "thinking_budget", None) is not None:
        return True

    extra = getattr(request, "extra_body", None)
    if not isinstance(extra, dict):
        return False

    thinking = extra.get("thinking")
    if isinstance(thinking, dict):
        t = thinking.get("type")
        if t == "enabled":
            return True
        if isinstance(t, str) and t.strip().lower() in {"enabled", "on", "true"}:
            return True
    elif isinstance(thinking, str) and thinking.strip().lower() in {
        "enabled",
        "on",
        "true",
    }:
        return True

    return False
