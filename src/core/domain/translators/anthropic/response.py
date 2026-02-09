from __future__ import annotations

import json
import logging
import time
from typing import Any

from src.core.domain.chat import (
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatResponse,
)
from src.core.domain.translation_utils.content_utils import coerce_reasoning_text
from src.core.domain.translation_utils.usage_utils import normalize_usage_metadata
from src.core.domain.usage_summary import UsageSummary

logger = logging.getLogger(__name__)


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
            usage=UsageSummary.from_dict(
                {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            ),
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
            normalized_reasoning = coerce_reasoning_text(reasoning_value)
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
    normalized_usage = normalize_usage_metadata(usage, "anthropic")

    return CanonicalChatResponse(
        id=response.get("id", f"chatcmpl-anthropic-{int(time.time())}"),
        object="chat.completion",
        created=int(time.time()),
        model=response.get("model", "unknown"),
        choices=choices,
        usage=UsageSummary.from_dict(normalized_usage) if normalized_usage else None,
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
            arguments_raw = tool_call.function.arguments or "{}"
            try:
                arguments = json.loads(arguments_raw)
            except json.JSONDecodeError as e:
                logger.debug(
                    "Failed to parse tool call arguments for %s: %s",
                    tool_call.function.name,
                    e,
                    exc_info=True,
                )
                arguments = {"_raw": arguments_raw}
            except Exception as e:
                logger.warning(
                    "Unexpected error parsing tool call arguments for %s: %s",
                    tool_call.function.name,
                    e,
                    exc_info=True,
                )
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
            "input_tokens": response.usage.prompt_tokens or 0,
            "output_tokens": response.usage.completion_tokens or 0,
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
