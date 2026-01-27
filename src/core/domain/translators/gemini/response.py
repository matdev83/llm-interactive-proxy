from __future__ import annotations

import json
from typing import Any

from src.core.domain.chat import (
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatResponse,
)
from src.core.domain.translation_utils.content_utils import (
    _coerce_reasoning_text,
    _safe_string,
)
from src.core.domain.translation_utils.tool_utils import _process_gemini_function_call
from src.core.domain.translation_utils.usage_utils import _normalize_usage_metadata
from src.core.domain.translators.gemini.finish_reason import map_gemini_finish_reason
from src.core.domain.usage_summary import UsageSummary


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

                # Pre-scan for thought signature
                thought_signature = None
                for part in parts:
                    if isinstance(part, dict):
                        sig = part.get("thoughtSignature") or part.get(
                            "thought_signature"
                        )
                        if sig:
                            thought_signature = sig
                            break

                text_parts: list[str] = []
                for part in parts:
                    if not isinstance(part, dict):
                        continue

                    # Prioritize explicit reasoning type
                    if part.get("type") in {"reasoning", "thinking"}:
                        normalized_reasoning = _coerce_reasoning_text(
                            part.get("text") or part.get("value")
                        )
                        if normalized_reasoning:
                            reasoning_segments.append(normalized_reasoning)
                        continue

                    if "text" in part and not part.get("functionCall"):
                        safe_text = _safe_string(part.get("text"))

                        # Check if metadata indicates this is also reasoning
                        metadata = part.get("metadata", {})
                        if isinstance(metadata, dict):
                            # Try to get reasoning from specific metadata fields first
                            metadata_reasoning = _coerce_reasoning_text(
                                metadata.get("thought")
                                or metadata.get("thinking")
                                or metadata.get("reasoning")
                            )

                            if metadata_reasoning:
                                reasoning_segments.append(metadata_reasoning)

                            meta_type = str(metadata.get("type", "")).lower()
                            if meta_type in {"thinking", "thought"} and safe_text:
                                # Avoid adding the same text twice if it was already added from metadata fields
                                if (
                                    not metadata_reasoning
                                    or metadata_reasoning != safe_text
                                ):
                                    reasoning_segments.append(safe_text)

                                # If it's explicitly marked as thinking/thought, don't treat it as regular content
                                continue

                        if safe_text:
                            text_parts.append(safe_text)
                    elif "functionCall" in part:
                        if tool_calls is None:
                            tool_calls = []

                        tool_calls.append(
                            _process_gemini_function_call(
                                part["functionCall"],
                                part=part,
                                thought_signature=thought_signature,
                            )
                        )

                content = "".join(text_parts)

            finish_reason = map_gemini_finish_reason(candidate.get("finishReason"))
            reasoning_text = "\n".join(
                segment for segment in reasoning_segments if segment
            ).strip()

            message_content: dict[str, Any] = {
                "role": "assistant",
                "content": content or None,
                "tool_calls": tool_calls,
            }
            if reasoning_text:
                message_content["reasoning_content"] = reasoning_text
                # Add aliases for compatibility
                message_content["reasoning"] = reasoning_text
                message_content["thinking"] = reasoning_text
                message_content["thought"] = reasoning_text

            choices.append(
                ChatCompletionChoice(
                    index=idx,
                    message=ChatCompletionChoiceMessage(**message_content),
                    finish_reason=finish_reason,
                )
            )

    usage_dict: dict[str, Any] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    if isinstance(response, dict) and "usageMetadata" in response:
        usage_metadata = response["usageMetadata"]
        usage_dict = _normalize_usage_metadata(usage_metadata, "gemini")

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
        usage=UsageSummary.from_dict(usage_dict) if usage_dict else None,
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
                        "args": json.loads(tool_call.function.arguments or "{}"),
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
                    response.usage.prompt_tokens or 0 if response.usage else 0
                ),
                "candidatesTokenCount": (
                    response.usage.completion_tokens or 0 if response.usage else 0
                ),
                "totalTokenCount": (
                    response.usage.total_tokens or 0 if response.usage else 0
                ),
            }
            if response.usage
            else {}
        ),
    }
