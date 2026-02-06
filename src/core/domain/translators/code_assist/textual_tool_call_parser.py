from __future__ import annotations

import json
import re
import uuid
from typing import Any

_TEXTUAL_TOOL_CALL_LINE_PATTERN = re.compile(
    r"^\s*tool[_ ]call:\s*([A-Za-z_][A-Za-z0-9_.:-]{0,63})(?:\s+(.*))?\s*$",
    re.IGNORECASE,
)
_KEY_VALUE_PATTERN = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)\s+(?:'([^']*)'|\"([^\"]*)\"|(\S+))"
)
_WHOLE_QUOTED_PATTERN = re.compile(r"""^(['"])(.*)\1$""")
_INTEGER_PATTERN = re.compile(r"^-?\d+$")
_FLOAT_PATTERN = re.compile(r"^-?\d+\.\d+$")
_COMMAND_LIKE_TOOLS = {
    "bash",
    "cmd",
    "execute_command",
    "run_command",
    "run_terminal_command",
    "shell",
    "terminal",
}


def parse_textual_tool_calls(content: str) -> tuple[str, list[dict[str, Any]]]:
    """Extract line-based textual tool calls and return cleaned content.

    Supported patterns:
    - ``tool_call: <name> for '<payload>'``
    - ``tool call: <name> key1 value1 key2 value2``
    - ``tool_call: <name> {"json": "args"}``
    """
    if not content:
        return content, []

    cleaned_lines: list[str] = []
    parsed_calls: list[dict[str, Any]] = []
    seen_calls: set[tuple[str, str]] = set()

    for line in content.splitlines():
        match = _TEXTUAL_TOOL_CALL_LINE_PATTERN.match(line)
        if not match:
            cleaned_lines.append(line)
            continue

        tool_name = match.group(1)
        remainder = (match.group(2) or "").strip()
        arguments = _parse_line_arguments(tool_name, remainder)
        dedup_key = (
            tool_name.lower(),
            json.dumps(arguments, ensure_ascii=False, sort_keys=True),
        )
        if dedup_key in seen_calls:
            continue
        seen_calls.add(dedup_key)

        parsed_calls.append(
            {
                "id": f"call_text_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            }
        )

    cleaned_content = "\n".join(cleaned_lines).strip()
    return cleaned_content, parsed_calls


def _parse_line_arguments(tool_name: str, remainder: str) -> dict[str, Any]:
    if not remainder:
        return {}

    normalized = remainder.strip()
    if normalized.lower().startswith("for "):
        normalized = normalized[4:].strip()

    if not normalized:
        return {}

    if normalized.startswith("{") and normalized.endswith("}"):
        try:
            parsed = json.loads(normalized)
            if isinstance(parsed, dict):
                return parsed
            return {"input": parsed}
        except json.JSONDecodeError:
            pass

    whole_quoted = _WHOLE_QUOTED_PATTERN.match(normalized)
    if whole_quoted:
        payload = whole_quoted.group(2)
        key = "command" if tool_name.lower() in _COMMAND_LIKE_TOOLS else "input"
        return {key: payload}

    key_values, has_key_values = _parse_key_value_arguments(normalized)
    if has_key_values:
        return key_values

    key = "command" if tool_name.lower() in _COMMAND_LIKE_TOOLS else "input"
    return {key: normalized}


def _parse_key_value_arguments(raw_value: str) -> tuple[dict[str, Any], bool]:
    arguments: dict[str, Any] = {}
    spans: list[tuple[int, int]] = []

    for match in _KEY_VALUE_PATTERN.finditer(raw_value):
        key = match.group(1)
        token = match.group(2) or match.group(3) or match.group(4) or ""
        arguments[key] = _coerce_scalar(token)
        spans.append(match.span())

    if not arguments:
        return {}, False

    remainder_chars = list(raw_value)
    for start, end in spans:
        for index in range(start, end):
            remainder_chars[index] = " "

    leftover = "".join(remainder_chars).strip(" ,;\t")
    if leftover:
        arguments["input"] = leftover

    return arguments, True


def _coerce_scalar(value: str) -> Any:
    normalized = value.strip()
    lowered = normalized.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    if _INTEGER_PATTERN.match(normalized):
        try:
            return int(normalized)
        except ValueError:
            return normalized
    if _FLOAT_PATTERN.match(normalized):
        try:
            return float(normalized)
        except ValueError:
            return normalized
    return normalized
