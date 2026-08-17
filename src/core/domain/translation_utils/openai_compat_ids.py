"""Normalize OpenAI-compatible ``id`` fields for strict clients and Pydantic models.

Some OpenAI-compatible gateways (e.g. certain NIM deployments) emit numeric or
null completion ids or tool-call ids. Downstream parsers (including Vercel AI SDK)
expect string ids on chat completion objects and stream chunks.
"""

from __future__ import annotations

import time
from typing import Any


def openai_created_int_fallback(created_raw: Any) -> int | None:
    """Best-effort int ``created`` for completion id fallbacks (mirrors SSE serializer)."""

    if isinstance(created_raw, int) and not isinstance(created_raw, bool):
        return created_raw
    if isinstance(created_raw, float) and created_raw.is_integer():
        return int(created_raw)
    return None


def sanitize_openai_compatible_sse_payload_inplace(payload: dict[str, Any]) -> None:
    """Coerce OpenAI-style ``id`` / tool-call ids on dicts about to be sent as SSE JSON.

    Covers escape hatches that ``json.dumps`` dicts without ``SSESerializer`` (error
    passthrough, backend stream formatting, injected terminal chunks).

    **Call contract:** Only invoke this on payloads that are already intended to be
    OpenAI Chat Completions / SSE-compatible (same paths for every backend that
    speaks that wire format). It is not used for Anthropic-native or other
    non-OpenAI-shaped event payloads.
    """

    obj = payload.get("object")
    has_choices = "choices" in payload
    is_chat_object = isinstance(obj, str) and obj.startswith("chat.completion")
    # Terminal usage frames from some OpenAI-compatible hosts (incl. certain NIM
    # deployments) carry ``usage`` but omit ``choices`` and sometimes ``object``.
    # Without this branch, numeric/null top-level ``id`` reaches strict clients unchanged.
    has_usage_dict = isinstance(payload.get("usage"), dict)
    has_error = isinstance(payload.get("error"), dict)
    raw_id = payload.get("id")
    bad_id = "id" in payload and not isinstance(raw_id, str)

    if not (has_choices or is_chat_object or has_usage_dict or (has_error and bad_id)):
        return

    payload["id"] = coerce_openai_completion_id(
        payload.get("id"),
        created_fallback=openai_created_int_fallback(payload.get("created")),
    )
    if has_choices:
        sanitize_openai_chunk_tool_call_ids_inplace(payload)
        sanitize_openai_chunk_delta_inplace(payload)


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


def sanitize_openai_chunk_delta_inplace(chunk: dict[str, Any]) -> None:
    """Normalize ``choices[].delta`` (and message) for clean streaming SSE rendering.

    - Removes keys with ``None`` values (e.g. role: None, content: None, refusal: None, tool_calls: None).
    - If ``reasoning_content`` (or ``reasoning``) or ``tool_calls`` is present, removes empty string ``content: ""``.
    - Drops internal/duplicate reasoning aliases (such as ``reasoning_summary``) when ``reasoning_content`` is present.
    """
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

            # Remove all None-valued keys to prevent polluting the delta
            none_keys = [k for k, v in container.items() if v is None]
            for k in none_keys:
                del container[k]

            # If reasoning or tool calls are present, omit empty string content
            has_reasoning = bool(
                container.get("reasoning_content")
                or container.get("reasoning")
                or container.get("reasoning_summary")
            )
            has_tools = bool(container.get("tool_calls"))
            if (has_reasoning or has_tools) and container.get("content") == "":
                container.pop("content", None)

            # Drop internal reasoning_summary alias if reasoning_content is already present
            if container.get("reasoning_content") and "reasoning_summary" in container:
                container.pop("reasoning_summary", None)
