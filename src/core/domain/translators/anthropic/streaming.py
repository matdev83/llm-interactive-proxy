from __future__ import annotations

import json
from typing import Any


def anthropic_to_domain_stream_chunk(chunk: Any) -> dict[str, Any]:
    """Translate an Anthropic streaming chunk to a canonical dictionary format."""
    import json
    import time
    import uuid

    if isinstance(chunk, str):
        chunk = chunk.strip()

        if "data: [DONE]" in chunk or chunk == "[DONE]":
            return {
                "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "claude-3-opus-20240229",
                "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
            }

        data_line = None
        for line in chunk.split("\n"):
            line = line.strip()
            if line.startswith("data:"):
                data_line = line[5:].strip()
                break

        if data_line is None:
            if chunk.startswith(("event:", "id:")) or not chunk:
                return {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "claude-3-opus-20240229",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
                }
            data_line = chunk

        try:
            chunk = json.loads(data_line)
        except json.JSONDecodeError:
            return {"error": "Invalid chunk format: expected a dictionary"}

    if not isinstance(chunk, dict):
        return {"error": "Invalid chunk format: expected a dictionary"}

    response_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
    created = int(time.time())
    model = "claude-3-opus-20240229"

    content = ""
    reasoning_content = ""
    finish_reason = None
    role = None

    event_type = chunk.get("type")

    if event_type == "message_start":
        role = "assistant"
    elif event_type == "content_block_delta":
        delta = chunk.get("delta", {})
        delta_type = delta.get("type")
        if delta_type == "text_delta":
            content = delta.get("text", "")
        elif delta_type in {"thinking_delta", "reasoning_delta"}:
            reasoning_content = (
                delta.get("thinking")
                or delta.get("reasoning")
                or delta.get("text")
                or ""
            )
    elif event_type == "message_delta":
        delta = chunk.get("delta", {})
        stop_reason = delta.get("stop_reason")
        if stop_reason == "end_turn":
            finish_reason = "stop"
        elif stop_reason == "max_tokens":
            finish_reason = "length"
        elif stop_reason == "tool_use":
            finish_reason = "tool_calls"
    elif event_type == "message_stop":
        finish_reason = "stop"

    output_delta: dict[str, Any] = {}
    if role:
        output_delta["role"] = role
    if content:
        output_delta["content"] = content
    if reasoning_content:
        output_delta["reasoning_content"] = reasoning_content
        output_delta["reasoning"] = reasoning_content

    return {
        "id": response_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {"index": 0, "delta": output_delta, "finish_reason": finish_reason}
        ],
    }


def _extract_content_from_domain_chunk(chunk: Any) -> str:
    choices = getattr(chunk, "choices", None)
    if choices and isinstance(choices, list) and len(choices) > 0:
        choice = choices[0]
        if isinstance(choice, dict):
            delta = choice.get("delta", {})
            if isinstance(delta, dict) and "content" in delta:
                return delta.get("content", "") or ""
        elif hasattr(choice, "delta"):
            delta = getattr(choice, "delta", None)
            if delta:
                if isinstance(delta, dict):
                    return delta.get("content", "") or ""
                if hasattr(delta, "content"):
                    return getattr(delta, "content", "") or ""

    return getattr(chunk, "content", "") or ""


def from_domain_to_anthropic_stream_chunk(chunk: Any) -> dict[str, Any]:
    """Translates a domain stream chunk to an Anthropic stream format."""
    content = _extract_content_from_domain_chunk(chunk)

    # Handle reasoning/thinking
    reasoning = None
    choices = getattr(chunk, "choices", None)
    if choices and isinstance(choices, list) and len(choices) > 0:
        choice = choices[0]
        delta = getattr(choice, "delta", None)
        if delta:
            reasoning = (
                delta.get("reasoning_content")
                if isinstance(delta, dict)
                else getattr(delta, "reasoning_content", None)
            )
            if not reasoning:
                reasoning = (
                    delta.get("reasoning")
                    if isinstance(delta, dict)
                    else getattr(delta, "reasoning", None)
                )

    if reasoning:
        return {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": reasoning},
        }

    # Handle tool calls
    if choices and isinstance(choices, list) and len(choices) > 0:
        choice = choices[0]
        delta = getattr(choice, "delta", None)
        if delta:
            tool_calls = (
                delta.get("tool_calls")
                if isinstance(delta, dict)
                else getattr(delta, "tool_calls", None)
            )
            if tool_calls:
                tool_call = tool_calls[0]
                function_data = (
                    tool_call.get("function")
                    if isinstance(tool_call, dict)
                    else getattr(tool_call, "function", None)
                )
                if function_data:
                    name = (
                        function_data.get("name")
                        if isinstance(function_data, dict)
                        else getattr(function_data, "name", None)
                    )
                    args = (
                        function_data.get("arguments")
                        if isinstance(function_data, dict)
                        else getattr(function_data, "arguments", None)
                    )
                    call_id = (
                        tool_call.get("id")
                        if isinstance(tool_call, dict)
                        else getattr(tool_call, "id", None)
                    )

                    if name and args and call_id:
                        return {
                            "type": "content_block_start",
                            "index": 0,
                            "content_block": {
                                "type": "tool_use",
                                "id": call_id,
                                "name": name,
                                "input": json.loads(args),
                            },
                        }

    return {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": content},
    }
