from __future__ import annotations

import json
import logging
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

from src.core.domain.chat import FunctionCall, ToolCall
from src.core.domain.translation_utils.json_utils import (
    sanitize_dict_for_json,
    sanitize_list_for_json,
)

logger = logging.getLogger(__name__)

# Responses / Codex item types that require a non-empty ``name``.
_NAMED_TOOL_ITEM_TYPES = frozenset(
    {
        "function_call",
        "custom_tool_call",
        "local_shell_call",
    }
)

# Responses / Codex item types that require a non-empty ``call_id``.
_CALL_ID_REQUIRED_ITEM_TYPES = frozenset(
    {
        "function_call",
        "function_call_output",
        "custom_tool_call",
        "custom_tool_call_output",
        "local_shell_call",
        "local_shell_call_output",
    }
)


def _coerce_responses_input_item(item: Any) -> dict[str, Any] | None:
    """Return a mutable dict copy of a Responses input item, if coercible."""
    if isinstance(item, MutableMapping):
        return dict(item)
    model_dump = getattr(item, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(exclude_none=False)
        if isinstance(dumped, dict):
            return dumped
    if isinstance(item, Mapping):
        return dict(item)
    return None


def is_nonempty_tool_name(value: Any) -> bool:
    """Return True when ``value`` is a usable tool/function name."""
    return isinstance(value, str) and bool(value.strip())


def extract_tool_call_name(tool_call: Any) -> str | None:
    """Extract a tool/function name from a chat ``tool_calls`` entry."""
    if isinstance(tool_call, Mapping):
        function = tool_call.get("function")
        if isinstance(function, Mapping):
            name = function.get("name")
            if isinstance(name, str):
                return name
        name = tool_call.get("name")
        return name if isinstance(name, str) else None
    function = getattr(tool_call, "function", None)
    if function is not None:
        name = (
            function.get("name")
            if isinstance(function, Mapping)
            else getattr(function, "name", None)
        )
        if isinstance(name, str):
            return name
    name = getattr(tool_call, "name", None)
    return name if isinstance(name, str) else None


def extract_tool_call_id(tool_call: Any) -> str | None:
    """Extract a tool-call id from a chat ``tool_calls`` entry."""
    if isinstance(tool_call, Mapping):
        call_id = tool_call.get("id") or tool_call.get("call_id")
        return call_id if isinstance(call_id, str) else None
    call_id = getattr(tool_call, "id", None) or getattr(tool_call, "call_id", None)
    return call_id if isinstance(call_id, str) else None


def sanitize_chat_messages_for_empty_tool_names(
    messages: Sequence[Any],
) -> tuple[list[Any], int]:
    """Drop chat tool calls/results with empty names or empty tool_call ids.

    Clients (for example pi) sometimes replay a garbage second ``tool_calls``
    entry with ``name=""`` and fragment arguments like ``\"}\"``. Upstream
    backends (DeepSeek chat/completions, Codex Responses, etc.) reject those
    with HTTP 400. Strip them generically rather than per-backend.
    """
    if not isinstance(messages, list | tuple):
        return list(messages) if messages else [], 0

    sanitized: list[Any] = []
    removed = 0
    for message in messages:
        if not isinstance(message, MutableMapping):
            sanitized.append(message)
            continue

        msg = dict(message)
        role = str(msg.get("role") or "").strip().casefold()

        # Optional message.name must be non-empty when present.
        if "name" in msg and not is_nonempty_tool_name(msg.get("name")):
            msg.pop("name", None)
            removed += 1

        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            kept_calls: list[Any] = []
            for tool_call in tool_calls:
                if is_nonempty_tool_name(extract_tool_call_name(tool_call)):
                    kept_calls.append(tool_call)
                else:
                    removed += 1
            if kept_calls:
                msg["tool_calls"] = kept_calls
            else:
                msg.pop("tool_calls", None)

        if role in {"tool", "function"}:
            tool_call_id = msg.get("tool_call_id")
            if not is_nonempty_tool_name(tool_call_id):
                # Empty tool_call_id is almost always an orphan for a dropped
                # unnamed tool call (e.g. pi "Tool  not found" stub).
                removed += 1
                continue

        sanitized.append(msg)

    return sanitized, removed


def sanitize_responses_input_for_empty_names(
    input_items: Sequence[Any],
) -> tuple[list[Any], int]:
    """Drop Responses ``input`` items that would 400 on empty ``name``/``call_id``.

    Accepts plain dicts and Pydantic models (``CodexInputItem``). Opaque
    non-mapping items are preserved unchanged.
    """
    if not isinstance(input_items, list | tuple):
        return list(input_items) if input_items else [], 0

    sanitized: list[Any] = []
    removed = 0
    for item in input_items:
        entry = _coerce_responses_input_item(item)
        if entry is None:
            sanitized.append(item)
            continue

        item_type = str(entry.get("type") or "").strip().casefold()

        # Optional message.name must not be an empty string.
        if "name" in entry and not is_nonempty_tool_name(entry.get("name")):
            if item_type in _NAMED_TOOL_ITEM_TYPES:
                removed += 1
                continue
            entry.pop("name", None)
            removed += 1

        if item_type in _NAMED_TOOL_ITEM_TYPES and not is_nonempty_tool_name(
            entry.get("name")
        ):
            removed += 1
            continue

        if item_type in _CALL_ID_REQUIRED_ITEM_TYPES and not is_nonempty_tool_name(
            entry.get("call_id")
        ):
            # pi and similar harnesses replay orphan tool results with
            # call_id="" / "Tool  not found"; Codex rejects empty_string.
            removed += 1
            continue

        sanitized.append(entry)

    return sanitized, removed


def normalize_tool_arguments(args: Any) -> str:
    """Normalize tool call arguments to a JSON string."""
    if args is None:
        return "{}"

    if isinstance(args, str):
        stripped = args.strip()
        if not stripped:
            return "{}"

        try:
            json.loads(stripped)
            return stripped
        except json.JSONDecodeError as _e:
            # Invalid JSON - try to fix common issues
            # Log for debugging to help identify problematic tool argument patterns
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Tool arguments string is not valid JSON; attempting repair",
                    exc_info=True,
                    extra={
                        "args_preview": (
                            stripped[:200]
                            if len(stripped) <= 200
                            else stripped[:200] + "..."
                        )
                    },
                )

        try:
            fixed_string = stripped.replace("'", '"')
            json.loads(fixed_string)
            return fixed_string
        except (json.JSONDecodeError, TypeError) as _e:
            # Unfixable JSON - return empty object
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Tool arguments string cannot be repaired; returning empty object",
                    exc_info=True,
                    extra={
                        "args_preview": (
                            stripped[:200]
                            if len(stripped) <= 200
                            else stripped[:200] + "..."
                        )
                    },
                )
            return "{}"

    if isinstance(args, dict):
        try:
            return json.dumps(args)
        except TypeError:
            sanitized_dict = sanitize_dict_for_json(args)
            return json.dumps(sanitized_dict)

    if isinstance(args, list | tuple):
        try:
            return json.dumps(args if isinstance(args, list) else list(args))
        except TypeError:
            sanitized_list = sanitize_list_for_json(
                args if isinstance(args, list) else list(args)
            )
            return json.dumps(sanitized_list)

    if isinstance(args, int | float | bool):
        return json.dumps(args)

    return "{}"


def process_gemini_function_call(
    function_call: dict[str, Any],
    part: dict[str, Any] | None = None,
    thought_signature: str | None = None,
) -> ToolCall:
    """Process a Gemini function call part into a ToolCall."""
    import uuid

    name = function_call.get("name", "")
    call_id = function_call.get("id") or f"call_{uuid.uuid4().hex[:12]}"
    raw_args = function_call.get("args", function_call.get("arguments"))
    normalized_args = normalize_tool_arguments(raw_args)

    extra_content: dict[str, Any] | None = None
    thought_sig = thought_signature
    if part is not None and not thought_sig:
        thought_sig = part.get("thoughtSignature") or part.get("thought_signature")

    if thought_sig:
        extra_content = {"google": {"thought_signature": thought_sig}}

    return ToolCall(
        id=call_id,
        type="function",
        function=FunctionCall(name=name, arguments=normalized_args),
        extra_content=extra_content,
    )
