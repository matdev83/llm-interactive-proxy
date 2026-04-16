"""ACP tool-call helpers: payload coalescing, byte sizes, and compact summaries."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

_TERMINAL_TOOL_STATUSES = frozenset(
    {
        "completed",
        "complete",
        "failed",
        "error",
        "cancelled",
        "canceled",
        "rejected",
        "done",
    }
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def payload_utf8_byte_length(value: Any) -> int:
    """UTF-8 byte length of a JSON/stringified representation (no raw streaming)."""
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        return len(str(value).encode("utf-8"))


def format_acp_tool_status_line(status: str) -> str:
    return f"Status: {status.strip()}\n"


def format_acp_tool_completion_summary(
    tool_name: str,
    *,
    input_bytes: int,
    output_bytes: int,
    started_iso: str,
    ended_iso: str,
    elapsed_s: float,
) -> str:
    """Single compact block after a tool finishes (no raw I/O)."""
    lines = [
        f"Tool: {tool_name}",
        f"Input size: {input_bytes} bytes",
        f"Started: {started_iso}",
        f"Ended: {ended_iso} ({elapsed_s:.3f} s)",
        f"Output size: {output_bytes} bytes",
        "",
    ]
    return "\n".join(lines)


def format_transcript_assistant_tool_record(name: str, arguments: Any) -> str:
    """History text for an assistant tool call (sizes only)."""
    n = payload_utf8_byte_length(arguments)
    return f"Tool: {name}\nInput size: {n} bytes\n"


def format_transcript_tool_message_record(
    *,
    tool_call_id: str | None,
    name: str | None,
    content: Any,
) -> str:
    """History text for a ``role: tool`` message (output size only)."""
    label = (name or "").strip() or "tool"
    parts: list[str] = []
    if isinstance(tool_call_id, str) and tool_call_id.strip():
        parts.append(f"Tool call id: {tool_call_id.strip()}")
    parts.append(f"Tool: {label}")
    parts.append(f"Output size: {payload_utf8_byte_length(content)} bytes")
    parts.append("")
    return "\n".join(parts)


def is_terminal_tool_status(status: str | None) -> bool:
    if not isinstance(status, str) or not status.strip():
        return False
    return status.strip().lower() in _TERMINAL_TOOL_STATUSES


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
    update: dict[str, Any],
) -> dict[str, Any]:
    """Like :func:`coalesce_acp_tool_session_dict` but overlays ``toolCallUpdate``."""
    base = coalesce_acp_tool_session_dict(update)
    tu = update.get("toolCallUpdate") or update.get("tool_call_update")
    if isinstance(tu, dict):
        return {**base, **tu}
    return base


def acp_tool_payload_should_emit(tc: dict[str, Any]) -> bool:
    """False for empty heartbeats."""
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
