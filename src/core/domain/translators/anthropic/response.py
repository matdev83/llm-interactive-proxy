from __future__ import annotations

import json
import time
from typing import Any

from src.core.domain.chat import (
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatResponse,
)
from src.core.domain.translation_utils.content_utils import _coerce_reasoning_text
from src.core.domain.translation_utils.usage_utils import _normalize_usage_metadata


def anthropic_to_domain_response(response: Any) -> CanonicalChatResponse:
    """Translate an Anthropic response to a CanonicalChatResponse."""
    if not isinstance(response, dict):
        return CanonicalChatResponse(
            id=f"chatcmpl-anthropic-{int(time.time())}",
            object="chat.completion",
            created=int(time.time()),
            model="unknown",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(
                        role="assistant", content=str(response)
                    ),
                    finish_reason="stop",
                )
            ],
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )

    content_blocks = response.get("content") or []
    text_segments: list[str] = []
    reasoning_segments: list[str] = []

    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text_value = block.get("text")
            if isinstance(text_value, str):
                text_segments.append(text_value)
        elif block_type in {"thinking", "reasoning"}:
            reasoning_value = (
                block.get("thinking")
                or block.get("text")
                or block.get("value")
                or block
            )
            normalized_reasoning = _coerce_reasoning_text(reasoning_value)
            if normalized_reasoning:
                reasoning_segments.append(normalized_reasoning)

    aggregated_text = "".join(text_segments).strip()
    reasoning_text = "\n".join(
        segment for segment in reasoning_segments if segment
    ).strip()

    message = ChatCompletionChoiceMessage(
        role=response.get("role", "assistant"),
        content=aggregated_text or None,
        reasoning_content=reasoning_text or None,
    )

    choices = [
        ChatCompletionChoice(
            index=0,
            message=message,
            finish_reason=response.get("stop_reason", "stop"),
        )
    ]

    usage = response.get("usage", {})
    normalized_usage = _normalize_usage_metadata(usage, "anthropic")

    return CanonicalChatResponse(
        id=response.get("id", f"chatcmpl-anthropic-{int(time.time())}"),
        object="chat.completion",
        created=int(time.time()),
        model=response.get("model", "unknown"),
        choices=choices,
        usage=normalized_usage,
    )


def from_domain_to_anthropic_response(response: ChatResponse) -> dict[str, Any]:
    """Translate a domain ChatResponse to an Anthropic response format."""
    content_blocks: list[dict[str, Any]] = []

    first_choice = response.choices[0] if response.choices else None
    message = first_choice.message if first_choice else None

    if message and message.reasoning_content:
        content_blocks.append(
            {
                "type": "thinking",
                "thinking": message.reasoning_content,
                "signature": "llm-proxy",
            }
        )

    if message and message.content:
        content_blocks.append({"type": "text", "text": message.content})

    if message and message.tool_calls:
        for tool_call in message.tool_calls:
            arguments_raw = tool_call.function.arguments
            try:
                arguments = json.loads(arguments_raw)
            except Exception:
                arguments = {"_raw": arguments_raw}

            content_blocks.append(
                {
                    "type": "tool_use",
                    "id": tool_call.id,
                    "name": tool_call.function.name,
                    "input": arguments,
                }
            )

    stop_reason = first_choice.finish_reason if first_choice else "stop"

    usage: dict[str, Any] | None = None
    if response.usage:
        usage = {
            "input_tokens": response.usage.get("prompt_tokens", 0),
            "output_tokens": response.usage.get("completion_tokens", 0),
        }

    return {
        "id": response.id,
        "type": "message",
        "role": "assistant",
        "model": response.model,
        "content": content_blocks,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage,
    }
