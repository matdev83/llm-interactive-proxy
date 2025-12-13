from __future__ import annotations

import json
import logging
from typing import Any, cast

from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.domain import translation as translation_module
from src.core.domain.chat import FunctionCall, ToolCall
from src.core.domain.translation_utils.tool_call_state import (
    assign_tool_call_index,
    cache_function_name,
    get_cached_function_name,
    reset_tool_call_state,
)
from src.core.domain.translators.responses.streaming_parse import (
    parse_responses_stream_chunk,
)

logger = logging.getLogger(__name__)


def responses_to_domain_stream_chunk(chunk: Any) -> dict[str, Any]:
    """Translate an OpenAI Responses streaming chunk to canonical format."""
    import time
    import uuid

    def _extract_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            if "text" in value:
                return _extract_text(value["text"])
            if "content" in value:
                return _extract_text(value["content"])
            if "value" in value:
                return _extract_text(value["value"])
        if isinstance(value, list):
            parts = [_extract_text(v) for v in value]
            return "".join(part for part in parts if part)
        if value is None:
            return ""
        return str(value)

    parsed = parse_responses_stream_chunk(chunk)
    if parsed.error is not None:
        return parsed.error
    if parsed.chunk is None:
        return {"error": "Invalid chunk format: expected a dictionary"}

    chunk = parsed.chunk
    event_type_from_sse = parsed.event_type_from_sse

    response_payload = chunk.get("response")
    if isinstance(response_payload, dict):
        chunk_id = response_payload.get("id")
        created = response_payload.get("created")
        model = response_payload.get("model")
    else:
        chunk_id = None
        created = None
        model = None

    chunk_id = chunk_id or chunk.get("id") or f"resp-{uuid.uuid4().hex[:16]}"
    created = created or chunk.get("created") or int(time.time())
    model = model or chunk.get("model") or "unknown"
    object_type = chunk.get("object") or "response.chunk"
    index = chunk.get("index", 0)
    event_type = (
        (chunk.get("type") or event_type_from_sse or "").strip()
        if chunk.get("type") or event_type_from_sse
        else ""
    )

    if logger.isEnabledFor(TRACE_LEVEL):
        try:
            logger.log(
                TRACE_LEVEL,
                "Responses event type=%s payload=%s",
                event_type or "<none>",
                json.dumps(chunk)[:400],
            )
        except Exception:
            logger.log(
                TRACE_LEVEL,
                "Responses event type=%s payload=<non-serializable>",
                event_type or "<none>",
            )

    def _build_chunk(
        delta: dict[str, Any] | None = None,
        finish_reason: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": chunk_id,
            "object": object_type,
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": index,
                    "delta": delta or {},
                    "finish_reason": finish_reason,
                }
            ],
        }

    if event_type == "response.output_text.delta":
        delta_payload = chunk.get("delta")
        text = _extract_text(delta_payload)
        if not text:
            return _build_chunk()
        delta_map: dict[str, Any] = {"content": text}
        if isinstance(delta_payload, dict):
            role = delta_payload.get("role")
            if role:
                delta_map["role"] = role
        delta_map.setdefault("role", "assistant")
        return _build_chunk(delta_map)

    if event_type == "response.reasoning_summary_text.delta":
        summary_text = _extract_text(chunk.get("delta"))
        return _build_chunk({"reasoning_summary": summary_text})

    if event_type == "response.reasoning_text.delta":
        reasoning_text = _extract_text(chunk.get("delta"))
        return _build_chunk({"reasoning_content": reasoning_text})

    if event_type == "response.function_call_arguments.delta":
        call_id = chunk.get("item_id") or chunk.get("call_id")
        name = chunk.get("name") or ""
        delta_payload = chunk.get("delta") or {}
        if isinstance(delta_payload, str):
            arguments_fragment = delta_payload
        else:
            arguments_fragment = _extract_text(delta_payload)
            if not isinstance(arguments_fragment, str):
                arguments_fragment = json.dumps(delta_payload)
        if arguments_fragment is None:
            arguments_fragment = ""
        tool_index = assign_tool_call_index(
            chunk_id, chunk.get("output_index"), call_id
        )
        function_payload: dict[str, Any] = {"arguments": arguments_fragment}
        if name:
            function_payload["name"] = name
        delta = {
            "tool_calls": [
                {
                    "index": tool_index,
                    "id": call_id or "",
                    "type": "function",
                    "function": function_payload,
                }
            ]
        }
        return _build_chunk(delta)

    if event_type == "response.function_call_arguments.done":
        call_id = chunk.get("item_id") or chunk.get("call_id")
        name = chunk.get("name") or ""
        if not name and call_id:
            name = get_cached_function_name(call_id)
        arguments = chunk.get("arguments")
        if isinstance(arguments, dict | list):
            arguments = json.dumps(arguments)
        elif arguments is None:
            arguments = "{}"
        else:
            arguments = str(arguments)
        tool_index = assign_tool_call_index(
            chunk_id, chunk.get("output_index"), call_id
        )
        tool_call_obj = ToolCall(
            id=call_id or "",
            type="function",
            function=FunctionCall(name=name, arguments=arguments),
        )
        tool_text = translation_module.render_tool_call(tool_call_obj)
        delta = {
            "tool_calls": [
                {
                    "index": tool_index,
                    "id": call_id or "",
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }
            ]
        }
        if tool_text:
            delta["_tool_call_text"] = tool_text  # type: ignore[assignment]
        return _build_chunk(delta, "tool_calls")

    if event_type == "response.output_item.done":
        item = chunk.get("item") or {}
        item_type = item.get("type")

        if logger.isEnabledFor(TRACE_LEVEL):
            try:
                logger.log(
                    TRACE_LEVEL,
                    "Responses output_item.done item=%s",
                    json.dumps(item)[:400],
                )
            except Exception:
                logger.log(
                    TRACE_LEVEL,
                    "Responses output_item.done item=<non-serializable>",
                )

        if item_type == "message":
            role = item.get("role")
            if role:
                return _build_chunk({"role": role})
            return _build_chunk()

        if item_type == "function_call":
            arguments = item.get("arguments", "{}")
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments)
            call_id = (
                item.get("call_id") or item.get("id") or f"call_{uuid.uuid4().hex[:8]}"
            )
            tool_index = assign_tool_call_index(
                chunk_id, chunk.get("output_index"), call_id
            )
            tool_call_obj = ToolCall(
                id=call_id,
                type="function",
                function=FunctionCall(name=item.get("name", ""), arguments=arguments),
            )
            tool_text = translation_module.render_tool_call(tool_call_obj)
            delta = {
                "tool_calls": [
                    {
                        "id": call_id,
                        "index": tool_index,
                        "type": "function",
                        "function": {
                            "name": item.get("name", ""),
                            "arguments": arguments,
                        },
                    }
                ]
            }
            if tool_text:
                delta["_tool_call_text"] = tool_text  # type: ignore[assignment]
            return _build_chunk(delta, "tool_calls")

        if item_type == "custom_tool_call":
            input_payload = item.get("input", "")
            if not isinstance(input_payload, str):
                input_payload = json.dumps(input_payload)
            call_id = (
                item.get("call_id")
                or item.get("id")
                or f"custom_{uuid.uuid4().hex[:8]}"
            )
            tool_index = assign_tool_call_index(
                chunk_id, chunk.get("output_index"), call_id
            )
            tool_call_obj = ToolCall(
                id=call_id,
                type="function",
                function=FunctionCall(
                    name=item.get("name", ""), arguments=input_payload
                ),
            )
            tool_text = translation_module.render_tool_call(tool_call_obj)
            delta = {
                "tool_calls": [
                    {
                        "id": call_id,
                        "index": tool_index,
                        "type": "function",
                        "function": {
                            "name": item.get("name", ""),
                            "arguments": input_payload or "{}",
                        },
                    }
                ]
            }
            if tool_text:
                delta["_tool_call_text"] = tool_text  # type: ignore[assignment]

            return _build_chunk(delta)

        if item_type == "local_shell_call":
            action = item.get("action") or {}
            arguments = action if isinstance(action, str) else json.dumps(action)
            call_id = (
                item.get("call_id") or item.get("id") or f"shell_{uuid.uuid4().hex[:8]}"
            )
            tool_index = assign_tool_call_index(
                chunk_id, chunk.get("output_index"), call_id
            )
            tool_call_obj = ToolCall(
                id=call_id,
                type="function",
                function=FunctionCall(name="shell", arguments=arguments),
            )
            tool_text = translation_module.render_tool_call(tool_call_obj)
            delta = {
                "tool_calls": [
                    {
                        "id": call_id,
                        "index": tool_index,
                        "type": "function",
                        "function": {"name": "shell", "arguments": arguments},
                    }
                ]
            }
            if tool_text:
                delta["_tool_call_text"] = tool_text  # type: ignore[assignment]

            return _build_chunk(delta)

        return _build_chunk()

    if event_type == "response.completed":
        response_info = chunk.get("response") or {}
        result = _build_chunk({}, "stop")
        usage = response_info.get("usage")
        if usage:
            result["usage"] = usage
        response_id = response_info.get("id") or chunk_id
        if response_id:
            result["response_id"] = response_id
            reset_tool_call_state(response_id)
        return result

    if event_type == "response.created":
        response_info = chunk.get("response") or {}
        response_id = response_info.get("id") or chunk_id
        if response_id:
            reset_tool_call_state(response_id)
        created_delta: dict[str, Any] = {}
        if response_id:
            created_delta["response_id"] = response_id
        created_delta["role"] = "assistant"
        return _build_chunk(created_delta or None)

    if event_type == "response.failed":
        response_info = chunk.get("response") or {}
        error_payload = response_info.get("error") or chunk.get("error") or {}
        reset_tool_call_state(response_info.get("id") or chunk_id)
        return {"error": "Responses stream reported failure", "details": error_payload}

    if event_type == "response.output_item.added":
        item = chunk.get("item") or {}
        item_type = item.get("type")

        if item_type == "function_call":
            call_id = (
                item.get("call_id") or item.get("id") or f"call_{uuid.uuid4().hex[:8]}"
            )
            name = item.get("name", "")

            cache_function_name(call_id, name)

            tool_index = assign_tool_call_index(
                chunk_id, chunk.get("output_index"), call_id
            )
            delta = {
                "tool_calls": [
                    {
                        "index": tool_index,
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": ""},
                    }
                ]
            }
            return _build_chunk(delta)
        return _build_chunk()

    if event_type in {
        "response.output_text.done",
        "response.custom_tool_call_input.done",
        "response.custom_tool_call_input.delta",
        "response.function_call_arguments.delta",
        "response.in_progress",
        "response.content_part.done",
    }:
        return _build_chunk()

    if "choices" in chunk:
        choices = chunk.get("choices") or []
        if not isinstance(choices, list) or not choices:
            return _build_chunk()

        primary_choice = choices[0] or {}
        finish_reason = primary_choice.get("finish_reason")
        raw_delta = primary_choice.get("delta") or {}
        if isinstance(raw_delta, dict):
            delta = cast(dict[str, Any], dict(raw_delta))
        else:
            delta = {"content": cast(Any, str(raw_delta))}

        content_value = delta.get("content")
        if isinstance(content_value, list):
            text_parts: list[str] = []
            for part in content_value:
                if not isinstance(part, dict):
                    continue
                part_type = part.get("type")
                if part_type in {"output_text", "text", "input_text"}:
                    text_value = part.get("text") or part.get("value") or ""
                    if text_value:
                        text_parts.append(str(text_value))
            delta["content"] = cast(Any, "".join(text_parts))
        elif isinstance(content_value, dict):
            delta["content"] = cast(Any, json.dumps(dict(content_value)))
        elif content_value is None:
            delta.pop("content", None)
        else:
            delta["content"] = cast(Any, str(content_value))

        tool_calls = delta.get("tool_calls")
        if isinstance(tool_calls, list):
            normalized_tool_calls: list[dict[str, Any]] = []
            for tool_call in tool_calls:
                if isinstance(tool_call, dict):
                    call_data = dict(tool_call)
                else:
                    function = getattr(tool_call, "function", None)
                    call_data = {
                        "id": getattr(tool_call, "id", ""),
                        "type": getattr(tool_call, "type", "function"),
                        "function": {
                            "name": getattr(function, "name", ""),
                            "arguments": getattr(function, "arguments", "{}"),
                        },
                    }

                function_payload = call_data.get("function") or {}
                if isinstance(function_payload, dict):
                    arguments = function_payload.get("arguments")
                    if isinstance(arguments, dict | list):
                        function_payload["arguments"] = json.dumps(arguments)
                    elif arguments is None:
                        function_payload["arguments"] = "{}"
                    else:
                        function_payload["arguments"] = str(arguments)

                normalized_tool_calls.append(call_data)

            if normalized_tool_calls:
                delta["tool_calls"] = normalized_tool_calls
            else:
                delta.pop("tool_calls", None)

        return _build_chunk(delta, finish_reason)

    return _build_chunk()


def from_domain_to_responses_stream_chunk(chunk: Any) -> dict[str, Any]:
    """Best-effort translation to Responses-style chunk schema."""
    from src.core.domain.translators.openai.streaming import (
        from_domain_to_openai_stream_chunk,
    )

    payload = from_domain_to_openai_stream_chunk(chunk)
    payload = dict(payload)
    payload["object"] = "response.chunk"
    return payload
