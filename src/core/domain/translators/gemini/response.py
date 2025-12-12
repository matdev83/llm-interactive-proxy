from __future__ import annotations

import json
from typing import Any

from src.core.domain.chat import (
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatResponse,
)
from src.core.domain.translation_utils.content_utils import _coerce_reasoning_text
from src.core.domain.translation_utils.tool_utils import _process_gemini_function_call
from src.core.domain.translation_utils.usage_utils import _normalize_usage_metadata
from src.core.domain.translators.gemini.finish_reason import map_gemini_finish_reason


def gemini_to_domain_response(response: Any) -> CanonicalChatResponse:
    """Translate a Gemini response to a CanonicalChatResponse."""
    import time
    import uuid

    response_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
    created = int(time.time())
    model = "gemini-pro"

    choices: list[ChatCompletionChoice] = []
    if isinstance(response, dict) and "candidates" in response:
        for idx, candidate in enumerate(response["candidates"]):
            content = ""
            tool_calls = None
            reasoning_segments: list[str] = []

            if "content" in candidate and "parts" in candidate["content"]:
                parts = candidate["content"]["parts"]

                text_parts: list[str] = []
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    if "text" in part and not part.get("functionCall"):
                        text_parts.append(part["text"])
                        metadata = part.get("metadata", {})
                        if isinstance(metadata, dict):
                            metadata_reasoning = _coerce_reasoning_text(
                                metadata.get("thought")
                                or metadata.get("thinking")
                                or metadata.get("reasoning")
                            )
                            if metadata_reasoning:
                                reasoning_segments.append(metadata_reasoning)
                            meta_type = str(metadata.get("type", "")).lower()
                            if meta_type in {"thinking", "thought"} and isinstance(
                                part.get("text"), str
                            ):
                                reasoning_segments.append(part["text"])
                    elif "functionCall" in part:
                        if tool_calls is None:
                            tool_calls = []

                        tool_calls.append(
                            _process_gemini_function_call(
                                part["functionCall"], part=part
                            )
                        )
                    elif part.get("type") in {"reasoning", "thinking"}:
                        normalized_reasoning = _coerce_reasoning_text(
                            part.get("text") or part.get("value")
                        )
                        if normalized_reasoning:
                            reasoning_segments.append(normalized_reasoning)

                content = "".join(text_parts)

            finish_reason = map_gemini_finish_reason(candidate.get("finishReason"))
            reasoning_text = "\n".join(
                segment for segment in reasoning_segments if segment
            ).strip()

            choices.append(
                ChatCompletionChoice(
                    index=idx,
                    message=ChatCompletionChoiceMessage(
                        role="assistant",
                        content=content or None,
                        reasoning_content=reasoning_text or None,
                        tool_calls=tool_calls,
                    ),
                    finish_reason=finish_reason,
                )
            )

    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if isinstance(response, dict) and "usageMetadata" in response:
        usage_metadata = response["usageMetadata"]
        usage = _normalize_usage_metadata(usage_metadata, "gemini")

    if not choices:
        choices = [
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionChoiceMessage(role="assistant", content=""),
                finish_reason="stop",
            )
        ]

    return CanonicalChatResponse(
        id=response_id,
        object="chat.completion",
        created=created,
        model=model,
        choices=choices,
        usage=usage,
    )


def from_domain_to_gemini_response(response: ChatResponse) -> dict[str, Any]:
    """Translates a domain ChatResponse to a Gemini response format."""
    candidates = []
    for choice in response.choices:
        if choice.message:
            parts: list[dict[str, Any]] = []
            if choice.message.reasoning_content:
                parts.append(
                    {"type": "reasoning", "text": choice.message.reasoning_content}
                )

            if choice.message.content:
                parts.append({"text": choice.message.content})

            if choice.message.tool_calls:
                for tool_call in choice.message.tool_calls:
                    function_call = {
                        "name": tool_call.function.name,
                        "args": json.loads(tool_call.function.arguments),
                    }
                    parts.append({"functionCall": function_call})

            candidates.append(
                {
                    "content": {"parts": parts, "role": choice.message.role},
                    "finishReason": (
                        choice.finish_reason.upper() if choice.finish_reason else "STOP"
                    ),
                    "index": choice.index,
                    "safetyRatings": [],
                }
            )

    return {
        "candidates": candidates,
        "promptFeedback": {"safetyRatings": []},
        "usageMetadata": (
            {
                "promptTokenCount": (
                    response.usage.get("prompt_tokens", 0) if response.usage else 0
                ),
                "candidatesTokenCount": (
                    response.usage.get("completion_tokens", 0) if response.usage else 0
                ),
                "totalTokenCount": (
                    response.usage.get("total_tokens", 0) if response.usage else 0
                ),
            }
            if response.usage
            else {}
        ),
    }
