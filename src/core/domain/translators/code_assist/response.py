from __future__ import annotations

import logging
from typing import Any

from src.core.domain.chat import (
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
)
from src.core.domain.translation_utils.tool_utils import _process_gemini_function_call
from src.core.domain.usage_summary import UsageSummary

logger = logging.getLogger(__name__)


def _map_gemini_finish_reason(finish_reason: str | None) -> str | None:
    if finish_reason is None:
        return None

    normalized = str(finish_reason).lower()
    mapping = {
        "stop": "stop",
        "max_tokens": "length",
        "safety": "content_filter",
        "tool_calls": "tool_calls",
    }
    return mapping.get(normalized, "stop")


def code_assist_to_domain_response(response: Any) -> CanonicalChatResponse:
    """
    Translate a Code Assist API response to a CanonicalChatResponse.

    The Code Assist API wraps the response in a "response" object and uses
    different structure than standard Gemini API.
    """
    import time

    if isinstance(response, CanonicalChatResponse):
        return response

    if not isinstance(response, dict):
        return CanonicalChatResponse(
            id=f"chatcmpl-code-assist-{int(time.time())}",
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

    response_wrapper = response.get("response", {})
    candidates = response_wrapper.get("candidates", [])
    generated_text = ""
    tool_calls: list[Any] = []
    finish_reason = "stop"

    if candidates and len(candidates) > 0:
        candidate = candidates[0]
        content = candidate.get("content") or {}
        parts = content.get("parts", [])

        if parts and len(parts) > 0:
            text_parts = []
            for part in parts:
                if isinstance(part, dict):
                    if "text" in part:
                        text_parts.append(part.get("text", ""))
                    elif "functionCall" in part:
                        try:
                            tool_calls.append(
                                _process_gemini_function_call(
                                    part["functionCall"], part=part
                                )
                            )
                        except (KeyError, TypeError, AttributeError, ValueError) as e:
                            # Expected data transformation errors - log and skip this tool call
                            if logger.isEnabledFor(logging.WARNING):
                                logger.warning(
                                    "Failed to process function call in Code Assist response, skipping: %s",
                                    e,
                                    exc_info=True,
                                )
                            continue
                        except Exception as e:
                            # Unexpected errors - log with full context but still skip to avoid breaking the response
                            if logger.isEnabledFor(logging.ERROR):
                                logger.error(
                                    "Unexpected error processing function call in Code Assist response, skipping: %s",
                                    e,
                                    exc_info=True,
                                )
                            continue
            generated_text = "".join(text_parts)

        if "finishReason" in candidate:
            finish_reason = (
                _map_gemini_finish_reason(candidate["finishReason"]) or "stop"
            )

    if tool_calls:
        finish_reason = "tool_calls"

    return CanonicalChatResponse(
        id=f"chatcmpl-code-assist-{int(time.time())}",
        object="chat.completion",
        created=int(time.time()),
        model=response.get("model", "code-assist-model"),
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionChoiceMessage(
                    role="assistant",
                    content=generated_text or None,
                    tool_calls=tool_calls if tool_calls else None,
                ),
                finish_reason=finish_reason,
            )
        ],
        usage=UsageSummary.from_dict(
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        ),
    )
