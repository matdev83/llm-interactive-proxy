from __future__ import annotations

import json
import logging
from typing import Any

from src.core.domain.chat import FunctionCall, ToolCall
from src.core.domain.translation_utils.json_utils import (
    _sanitize_dict_for_json,
    _sanitize_list_for_json,
)

logger = logging.getLogger(__name__)


def _normalize_tool_arguments(args: Any) -> str:
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
            sanitized_dict = _sanitize_dict_for_json(args)
            return json.dumps(sanitized_dict)

    if isinstance(args, list | tuple):
        try:
            return json.dumps(args if isinstance(args, list) else list(args))
        except TypeError:
            sanitized_list = _sanitize_list_for_json(
                args if isinstance(args, list) else list(args)
            )
            return json.dumps(sanitized_list)

    if isinstance(args, int | float | bool):
        return json.dumps(args)

    return "{}"


def _process_gemini_function_call(
    function_call: dict[str, Any], part: dict[str, Any] | None = None
) -> ToolCall:
    """Process a Gemini function call part into a ToolCall."""
    import uuid

    name = function_call.get("name", "")
    call_id = function_call.get("id") or f"call_{uuid.uuid4().hex[:12]}"
    raw_args = function_call.get("args", function_call.get("arguments"))
    normalized_args = _normalize_tool_arguments(raw_args)

    extra_content: dict[str, Any] | None = None
    if part is not None:
        thought_sig = part.get("thoughtSignature") or part.get("thought_signature")
        if thought_sig:
            extra_content = {"google": {"thought_signature": thought_sig}}

    return ToolCall(
        id=call_id,
        type="function",
        function=FunctionCall(name=name, arguments=normalized_args),
        extra_content=extra_content,
    )
