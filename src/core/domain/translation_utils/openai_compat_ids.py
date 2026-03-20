"""Normalize OpenAI-compatible ``id`` fields for strict clients and Pydantic models.

Some OpenAI-compatible gateways (e.g. certain NIM deployments) emit numeric or
null completion ids or tool-call ids. Downstream parsers (including Vercel AI SDK)
expect string ids on chat completion objects and stream chunks.
"""

from __future__ import annotations

import time
from typing import Any


def coerce_openai_completion_id(
    raw: Any,
    *,
    created_fallback: int | None = None,
) -> str:
    """Return a non-empty string completion id suitable for SSE / JSON responses."""

    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped:
            return stripped
    elif raw is not None and isinstance(raw, bool):
        return "true" if raw else "false"
    elif isinstance(raw, int) and not isinstance(raw, bool):
        return str(raw)
    elif isinstance(raw, float):
        if raw.is_integer():
            return str(int(raw))
        return str(raw)

    if isinstance(created_fallback, int) and created_fallback > 0:
        return f"chatcmpl-{created_fallback}"
    return f"chatcmpl-{int(time.time())}"


def normalize_tool_call_dict_id_inplace(tc: dict[str, Any]) -> None:
    """Coerce or drop a streaming tool-call fragment ``id`` for Pydantic / JSON safety."""

    if "id" not in tc:
        return
    tid = tc["id"]
    if tid is None or tid == "":
        tc.pop("id", None)
        return
    if isinstance(tid, str):
        return
    if isinstance(tid, bool):
        tc["id"] = "true" if tid else "false"
        return
    if isinstance(tid, int) and not isinstance(tid, bool):
        tc["id"] = str(tid)
        return
    if isinstance(tid, float) and tid.is_integer():
        tc["id"] = str(int(tid))
        return
    if isinstance(tid, float):
        tc["id"] = str(tid)
        return
    tc.pop("id", None)


def sanitize_openai_chunk_tool_call_ids_inplace(chunk: dict[str, Any]) -> None:
    """Normalize ``choices[].delta.tool_calls[].id`` (and message) on a raw chunk dict."""

    choices = chunk.get("choices")
    if not isinstance(choices, list):
        return
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        for key in ("delta", "message"):
            container = choice.get(key)
            if not isinstance(container, dict):
                continue
            tcs = container.get("tool_calls")
            if not isinstance(tcs, list):
                continue
            for item in tcs:
                if isinstance(item, dict):
                    normalize_tool_call_dict_id_inplace(item)
