from __future__ import annotations

import time
from typing import Any

from src.core.domain.chat import (
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatResponse,
    ToolCall,
)
from src.core.domain.translation_utils.content_utils import _coerce_reasoning_text
from src.core.domain.translation_utils.usage_utils import _normalize_usage_metadata
from src.core.domain.usage_summary import UsageSummary


def openai_to_domain_response(response: Any) -> CanonicalChatResponse:
    """Translate an OpenAI response to a CanonicalChatResponse."""
    if not isinstance(response, dict):
        return CanonicalChatResponse(
            id=f"chatcmpl-openai-{int(time.time())}",
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

    choices: list[ChatCompletionChoice] = []
    for idx, ch in enumerate(response.get("choices", [])):
        msg = ch.get("message", {})
        role = msg.get("role", "assistant")
        content = msg.get("content")

        tool_calls = None
        raw_tool_calls = msg.get("tool_calls")
        if isinstance(raw_tool_calls, list):
            validated_tool_calls = []
            for tc in raw_tool_calls:
                if isinstance(tc, dict):
                    try:
                        tool_call_obj = ToolCall(**tc)
                        validated_tool_calls.append(tool_call_obj)
                    except (TypeError, ValueError):
                        continue
                elif isinstance(tc, ToolCall):
                    validated_tool_calls.append(tc)
            tool_calls = validated_tool_calls if validated_tool_calls else None

        reasoning_content = msg.get("reasoning_content")
        if reasoning_content is None and "reasoning" in msg:
            reasoning_content = _coerce_reasoning_text(msg.get("reasoning"))
        if reasoning_content is None:
            metadata_reasoning = _coerce_reasoning_text(
                msg.get("metadata", {}).get("reasoning")
            )
            if metadata_reasoning:
                reasoning_content = metadata_reasoning
        if reasoning_content is None:
            choice_reasoning = _coerce_reasoning_text(
                ch.get("reasoning") or ch.get("metadata", {}).get("reasoning")
            )
            if choice_reasoning:
                reasoning_content = choice_reasoning

        refusal = msg.get("refusal")
        annotations = msg.get("annotations")

        message_obj = ChatCompletionChoiceMessage(
            role=role,
            content=content,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls,
            refusal=refusal,
            annotations=annotations,
        )

        logprobs = ch.get("logprobs")

        choices.append(
            ChatCompletionChoice(
                index=idx,
                message=message_obj,
                finish_reason=ch.get("finish_reason"),
                logprobs=logprobs,
            )
        )

    usage = response.get("usage") or {}
    normalized_usage = _normalize_usage_metadata(usage, "openai")

    return CanonicalChatResponse(
        id=response.get("id", "chatcmpl-openai-unk"),
        object=response.get("object", "chat.completion"),
        created=response.get("created", int(time.time())),
        model=response.get("model", "unknown"),
        choices=choices,
        usage=UsageSummary.from_dict(normalized_usage) if normalized_usage else None,
        service_tier=response.get("service_tier"),
    )


def from_domain_to_openai_response(response: ChatResponse) -> dict[str, Any]:
    """Translate a domain ChatResponse to an OpenAI response format."""
    from src.core.domain.chat import (
        ChatCompletionChoice as _Choice,
    )
    from src.core.domain.chat import (
        ChatCompletionChoiceMessage as _Message,
    )
    from src.core.domain.chat import (
        ChatResponse as _Response,
    )

    openai_choices = []
    for choice in response.choices:
        message = _Message(
            role=choice.message.role,
            content=choice.message.content,
            reasoning_content=choice.message.reasoning_content,
            tool_calls=(
                choice.message.tool_calls if choice.message.tool_calls else None
            ),
        )
        openai_choice = _Choice(
            index=choice.index,
            message=message,
            finish_reason=choice.finish_reason,
        )
        openai_choices.append(openai_choice)

    openai_response = _Response(
        id=response.id,
        created=response.created,
        model=response.model,
        choices=openai_choices,
        usage=response.usage,
    )

    response_dict: dict[str, Any] = openai_response.model_dump()
    for choice in response_dict.get("choices", []):
        if not isinstance(choice, dict):
            continue
        message_payload = choice.get("message")
        if (
            isinstance(message_payload, dict)
            and message_payload.get("reasoning_content")
            and "reasoning" not in message_payload
        ):
            message_payload["reasoning"] = message_payload["reasoning_content"]
    return response_dict
