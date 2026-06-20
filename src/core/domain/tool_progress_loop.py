"""Domain types for cross-request tool-progress loop detection."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import PureWindowsPath
from typing import Any, Literal


class ToolProgressLoopAction(str, Enum):
    """Decision action returned by the tool-progress loop guard."""

    ALLOW = "allow"
    BLOCK = "block"
    STEER = "steer"


ToolProgressLoopGuardActionMode = Literal["error", "steer_then_error"]

DEFAULT_TOOL_PROGRESS_LOOP_GUARD_ACTION: ToolProgressLoopGuardActionMode = (
    "steer_then_error"
)

DEFAULT_TOOL_PROGRESS_LOOP_STEERING_MESSAGE = (
    "You appear to be repeating the same tool call without making progress. "
    "Try a different approach, summarize what you've learned, or ask for guidance. "
    "If you repeat the exact same tool call with the same arguments again, "
    "this session will be stopped."
)


@dataclass(frozen=True, slots=True)
class ToolCallFingerprint:
    """Stable identifiers for a tool call and its argument shape."""

    tool_name: str
    arguments_hash: str
    arguments_shape_hash: str
    target_resource: str | None = None
    normalized_preview: str | None = None


@dataclass(frozen=True, slots=True)
class ToolOutputFingerprint:
    """Stable identifiers for a tool result payload."""

    output_hash: str
    output_shape_hash: str
    kind: Literal["empty", "error", "no_match", "success"]
    size_bucket: Literal["empty", "small", "medium", "large", "huge"]
    normalized_preview: str | None = None


@dataclass(frozen=True, slots=True)
class ToolProgressLoopDecision:
    """Outcome of evaluating a session for tool-progress loops."""

    action: ToolProgressLoopAction
    reason: str | None = None
    score: int = 0
    repeated_call_count: int = 0
    repeated_output_count: int = 0
    steering_message: str | None = None

    @property
    def allow(self) -> bool:
        return self.action == ToolProgressLoopAction.ALLOW


def fingerprint_tool_call(tool_call: Any) -> ToolCallFingerprint:
    """Return a stable fingerprint for a tool call-like payload."""
    tool_name, arguments = _extract_tool_call_parts(tool_call)
    parsed = _parse_arguments(arguments)
    normalized = _normalize_argument_value(parsed, normalize_volatile=False)
    shape = _normalize_argument_value(parsed, normalize_volatile=True)
    target_resource = _extract_target_resource(tool_name, parsed)
    preview = _preview(normalized)
    return ToolCallFingerprint(
        tool_name=tool_name,
        arguments_hash=_hash_json([tool_name, normalized]),
        arguments_shape_hash=_hash_json([tool_name, shape]),
        target_resource=target_resource,
        normalized_preview=preview,
    )


def fingerprint_tool_output(output: Any) -> ToolOutputFingerprint:
    """Return a stable fingerprint for a tool output-like payload."""
    text = _stringify(output)
    normalized = _normalize_output_text(text)
    return ToolOutputFingerprint(
        output_hash=_hash_text(normalized),
        output_shape_hash=_hash_text(_shape_output_text(normalized)),
        kind=_classify_output(normalized),
        size_bucket=_size_bucket(normalized),
        normalized_preview=_preview(normalized),
    )


def _extract_tool_call_parts(tool_call: Any) -> tuple[str, Any]:
    function = getattr(tool_call, "function", None)
    if function is None and isinstance(tool_call, dict):
        function = tool_call.get("function")
    name = getattr(function, "name", None)
    arguments = getattr(function, "arguments", None)
    if isinstance(function, dict):
        name = function.get("name", name)
        arguments = function.get("arguments", arguments)
    return str(name or "unknown"), arguments if arguments is not None else "{}"


def _parse_arguments(arguments: Any) -> Any:
    if not isinstance(arguments, str):
        return arguments
    try:
        return json.loads(arguments)
    except (TypeError, ValueError):
        return arguments


def _normalize_argument_value(value: Any, *, normalize_volatile: bool) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0]).lower()):
            key_str = str(key)
            if normalize_volatile and _is_volatile_key(key_str):
                normalized[key_str] = "<volatile>"
            else:
                normalized[key_str] = _normalize_argument_value(
                    item, normalize_volatile=normalize_volatile
                )
        return normalized
    if isinstance(value, list):
        return [
            _normalize_argument_value(item, normalize_volatile=normalize_volatile)
            for item in value
        ]
    if isinstance(value, str):
        return _normalize_string_argument(value, normalize_volatile=normalize_volatile)
    return value


def _normalize_string_argument(value: str, *, normalize_volatile: bool) -> str:
    normalized = value.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", normalized):
        try:
            normalized = PureWindowsPath(normalized).as_posix().lower()
        except Exception:
            normalized = normalized.lower()
    if normalize_volatile:
        normalized = re.sub(
            r"(--(?:request-)?id\s+)[A-Za-z0-9_.:-]+",
            r"\1<volatile>",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"\b(?:req|call|msg|resp|fc)_[A-Za-z0-9_.:-]*\d[A-Za-z0-9_.:-]*\b",
            "<volatile>",
            normalized,
            flags=re.IGNORECASE,
        )
    return normalized


def _is_volatile_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in {
        "id",
        "request_id",
        "call_id",
        "message_id",
        "timestamp",
        "created_at",
    }


def _extract_target_resource(tool_name: str, parsed_arguments: Any) -> str | None:
    if not isinstance(parsed_arguments, dict):
        return None
    normalized_name = tool_name.lower()
    if normalized_name in {"read", "glob", "grep", "fff_grep", "fff_find_files"}:
        for key in ("filePath", "path", "query", "pattern"):
            value = parsed_arguments.get(key)
            if isinstance(value, str) and value:
                return _normalize_string_argument(value, normalize_volatile=False)
    if normalized_name == "apply_patch":
        patch_text = parsed_arguments.get("patchText")
        if isinstance(patch_text, str):
            matches = re.findall(
                r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", patch_text, re.MULTILINE
            )
            if matches:
                return ",".join(matches)
    return None


def _normalize_output_text(text: str) -> str:
    without_ansi = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    without_timestamps = re.sub(
        r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:,\d+)?\b",
        "<timestamp>",
        without_ansi,
    )
    without_times = re.sub(r"\b\d{2}:\d{2}:\d{2}\b", "<time>", without_timestamps)
    return re.sub(r"\s+", " ", without_times).strip()


def _shape_output_text(text: str) -> str:
    shaped = re.sub(r"\b[0-9a-f]{8,}\b", "<hex>", text, flags=re.IGNORECASE)
    shaped = re.sub(r"\b\d+\b", "<number>", shaped)
    return shaped


def _classify_output(text: str) -> Literal["empty", "error", "no_match", "success"]:
    if not text:
        return "empty"
    lowered = text.lower()
    if "no match" in lowered or "no results" in lowered or "0 matches" in lowered:
        return "no_match"
    if "error" in lowered or "exception" in lowered or "traceback" in lowered:
        return "error"
    return "success"


def _size_bucket(text: str) -> Literal["empty", "small", "medium", "large", "huge"]:
    length = len(text)
    if length == 0:
        return "empty"
    if length < 512:
        return "small"
    if length < 4096:
        return "medium"
    if length < 32768:
        return "large"
    return "huge"


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError, RecursionError):
        return str(value)


def _hash_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return _hash_text(payload)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()


def _preview(value: Any, max_chars: int = 160) -> str:
    text = _stringify(value)
    return text[:max_chars]
