"""Shared Markdown rendering for ACP tool invocations and results."""

from __future__ import annotations

import json
from typing import Any

# Per fenced field body (after formatting); avoids huge SSE / session/prompt payloads.
DEFAULT_MAX_MARKDOWN_FIELD_CHARS = 64_000

_TRUNCATION_NOTICE = "\n\n[truncated]"


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + _TRUNCATION_NOTICE


def normalize_display_value(value: Any, *, max_chars: int) -> str:
    """Coerce a value to a readable string for fenced Markdown blocks."""
    if value is None:
        return ""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                parsed = json.loads(stripped)
                return _truncate(
                    json.dumps(parsed, indent=2, ensure_ascii=False),
                    max_chars,
                )
            except json.JSONDecodeError:
                pass
        return _truncate(value, max_chars)
    try:
        return _truncate(
            json.dumps(value, indent=2, ensure_ascii=False),
            max_chars,
        )
    except (TypeError, ValueError):
        return _truncate(str(value), max_chars)


def _fence_run_length(body: str) -> int:
    max_run = 0
    run = 0
    for ch in body:
        if ch == "`":
            run += 1
            if run > max_run:
                max_run = run
        else:
            run = 0
    return max_run


def _fence(language: str, body: str) -> str:
    inner = body.rstrip("\n")
    fence_len = max(3, _fence_run_length(inner) + 1)
    fence = "`" * fence_len
    lang = language or ""
    return f"{fence}{lang}\n{inner}\n{fence}\n"


def format_tool_section(
    name: str,
    *,
    input_obj: Any | None = None,
    output_obj: Any | None = None,
    max_field_chars: int = DEFAULT_MAX_MARKDOWN_FIELD_CHARS,
) -> str:
    """Full block: horizontal rule, tool title, optional Input/Output fences."""
    parts: list[str] = ["---\n\n", f"**Tool: {name}**\n\n"]
    if input_obj is not None:
        input_text = normalize_display_value(input_obj, max_chars=max_field_chars)
        if input_text:
            parts.append("**Input:**\n\n")
            parts.append(_fence("json", input_text))
            parts.append("\n")
    if output_obj is not None:
        out_text = normalize_display_value(output_obj, max_chars=max_field_chars)
        if out_text:
            parts.append("**Output:**\n\n")
            parts.append(_fence("", out_text))
            parts.append("\n")
    return "".join(parts)


def format_tool_invocation_block(
    name: str,
    input_obj: Any | None,
    *,
    max_field_chars: int = DEFAULT_MAX_MARKDOWN_FIELD_CHARS,
) -> str:
    """Tool + Input only (start of a tool interaction on the content channel)."""
    return format_tool_section(
        name, input_obj=input_obj, output_obj=None, max_field_chars=max_field_chars
    )


def format_tool_output_fragment(
    output_obj: Any | None,
    *,
    status: str | None = None,
    max_field_chars: int = DEFAULT_MAX_MARKDOWN_FIELD_CHARS,
) -> str:
    """Continuation fragment: Output fence and/or status line (no Tool header)."""
    parts: list[str] = []
    if isinstance(status, str) and status.strip():
        parts.append(f"**Status:** {status.strip()}\n\n")
    if output_obj is not None:
        out_text = normalize_display_value(output_obj, max_chars=max_field_chars)
        if out_text:
            parts.append("**Output:**\n\n")
            parts.append(_fence("", out_text))
            parts.append("\n")
    return "".join(parts) if parts else ""


def _flatten_acp_tool_content_blocks(val: Any) -> Any | None:
    """ACP ``content`` on tool updates is a list of typed blocks; flatten to text."""
    if not isinstance(val, list) or not val:
        return None
    lines: list[str] = []
    for block in val:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "content":
            inner = block.get("content")
            if isinstance(inner, dict):
                if inner.get("type") == "text":
                    t = inner.get("text")
                    if isinstance(t, str) and t.strip():
                        lines.append(t.strip())
                else:
                    try:
                        lines.append(json.dumps(inner, indent=2, ensure_ascii=False))
                    except (TypeError, ValueError):
                        lines.append(str(inner))
            continue
        if btype == "diff":
            path = block.get("path", "")
            lines.append(
                f"[diff] {path}\n"
                f"--- old ---\n{block.get('oldText')}\n"
                f"+++ new ---\n{block.get('newText')}"
            )
            continue
        if btype == "terminal":
            tid = block.get("terminalId")
            lines.append(f"[terminal] {tid}")
            continue
        try:
            lines.append(json.dumps(block, indent=2, ensure_ascii=False))
        except (TypeError, ValueError):
            lines.append(str(block))
    if not lines:
        return None
    return "\n\n".join(lines)


_TOOL_ROOT_KEYS: tuple[str, ...] = (
    "toolCallId",
    "callId",
    "id",
    "title",
    "name",
    "toolName",
    "kind",
    "status",
    "state",
    "rawInput",
    "rawOutput",
    "rawArguments",
    "arguments",
    "input",
    "params",
    "args",
    "result",
    "output",
    "response",
    "function",
    "content",
    "locations",
)


def coalesce_acp_tool_session_dict(update: dict[str, Any]) -> dict[str, Any]:
    """Merge nested ``toolCall`` objects with flat ACP fields on the update dict."""
    merged: dict[str, Any] = {}
    nested = (
        update.get("toolCall")
        or update.get("tool_call")
        or update.get("toolInvocation")
    )
    if isinstance(nested, list):
        for it in nested:
            if isinstance(it, dict):
                merged.update(it)
    elif isinstance(nested, dict):
        merged.update(nested)

    for k in _TOOL_ROOT_KEYS:
        if k not in update:
            continue
        val = update[k]
        if val is None:
            continue
        merged.setdefault(k, val)
    return merged


def coalesce_acp_tool_call_update_session_dict(
    update: dict[str, Any]
) -> dict[str, Any]:
    """Like :func:`coalesce_acp_tool_session_dict` but overlays ``toolCallUpdate``."""
    base = coalesce_acp_tool_session_dict(update)
    tu = update.get("toolCallUpdate") or update.get("tool_call_update")
    if isinstance(tu, dict):
        return {**base, **tu}
    return base


def acp_tool_payload_should_emit(tc: dict[str, Any]) -> bool:
    """False for empty heartbeats that would only render ``Tool: tool`` noise."""
    if extract_tool_correlation_key(tc):
        return True
    if extract_tool_input(tc) is not None:
        return True
    if extract_tool_output(tc) is not None:
        return True
    st = tc.get("status") or tc.get("state")
    if isinstance(st, str) and st.strip():
        return True
    if isinstance(tc.get("title"), str) and tc["title"].strip():
        return True
    if isinstance(tc.get("name"), str) and tc["name"].strip():
        return True
    if isinstance(tc.get("kind"), str) and tc["kind"].strip():
        return True
    fn = tc.get("function")
    return bool(
        isinstance(fn, dict)
        and isinstance(fn.get("name"), str)
        and str(fn["name"]).strip()
    )


def extract_tool_name(tc: dict[str, Any]) -> str:
    title = tc.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    fn = tc.get("function")
    if isinstance(fn, dict):
        n = fn.get("name")
        if isinstance(n, str) and n.strip():
            return n.strip()
    for key in ("name", "toolName", "tool", "command", "functionName"):
        raw = tc.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    kind = tc.get("kind")
    if isinstance(kind, str) and kind.strip():
        return kind.strip()
    return "tool"


def extract_tool_input(tc: dict[str, Any]) -> Any | None:
    for k in ("rawInput", "rawArguments", "arguments", "input", "params", "args"):
        if k not in tc:
            continue
        val = tc.get(k)
        if val is not None and val != "":
            return val
    fn = tc.get("function")
    if isinstance(fn, dict) and "arguments" in fn:
        a = fn.get("arguments")
        if a is not None and a != "":
            return a
    return None


def extract_tool_output(tc: dict[str, Any]) -> Any | None:
    for k in ("rawOutput", "result", "output", "response"):
        if k not in tc:
            continue
        val = tc.get(k)
        if val is not None and val != "":
            return val
    if "content" in tc:
        flat = _flatten_acp_tool_content_blocks(tc.get("content"))
        if flat is not None:
            return flat
        val = tc.get("content")
        if val is not None and val != "":
            return val
    return None


def extract_tool_correlation_key(tc: dict[str, Any]) -> str | None:
    for k in ("toolCallId", "id", "callId"):
        v = tc.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


def format_transcript_tool_result(
    *,
    tool_call_id: str | None,
    name: str | None,
    content: Any,
    max_field_chars: int = DEFAULT_MAX_MARKDOWN_FIELD_CHARS,
) -> str:
    """Markdown for a ``role: tool`` message in session transcripts."""
    label_parts: list[str] = []
    if isinstance(name, str) and name.strip():
        label_parts.append(name.strip())
    if isinstance(tool_call_id, str) and tool_call_id.strip():
        label_parts.append(f"id={tool_call_id.strip()}")
    label = " / ".join(label_parts) if label_parts else "tool"
    body = normalize_display_value(content, max_chars=max_field_chars)
    parts = ["---\n\n", f"**Tool result ({label})**\n\n"]
    if body:
        parts.append("**Output:**\n\n")
        parts.append(_fence("", body))
        parts.append("\n")
    return "".join(parts)
