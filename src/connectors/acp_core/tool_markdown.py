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


def _fence(language: str, body: str) -> str:
    inner = body.rstrip("\n")
    return f"```{language}\n{inner}\n```\n"


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


def extract_tool_name(tc: dict[str, Any]) -> str:
    raw = tc.get("name") or tc.get("toolName") or tc.get("title") or "tool"
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return "tool"


def extract_tool_input(tc: dict[str, Any]) -> Any | None:
    for k in ("arguments", "input", "params", "args"):
        if k not in tc:
            continue
        val = tc.get(k)
        if val is not None and val != "":
            return val
    return None


def extract_tool_output(tc: dict[str, Any]) -> Any | None:
    for k in ("result", "output", "content", "response"):
        if k not in tc:
            continue
        val = tc.get(k)
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
