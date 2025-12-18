from __future__ import annotations

import time
from typing import Any

from src.core.domain.chat import (
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
)
from src.core.domain.translators.openai.response import openai_to_domain_response
from src.core.domain.usage_summary import UsageSummary


def raw_text_to_domain_response(response: Any) -> CanonicalChatResponse:
    """Translate a raw text response to a CanonicalChatResponse."""
    if isinstance(response, str):
        now = int(time.time())
        return CanonicalChatResponse(
            id=f"chatcmpl-raw-text-{now}",
            object="chat.completion",
            created=now,
            model="text-model",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(
                        role="assistant", content=response
                    ),
                    finish_reason="stop",
                )
            ],
            usage=UsageSummary.from_dict(
                {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            ),
        )
    return openai_to_domain_response(response)
