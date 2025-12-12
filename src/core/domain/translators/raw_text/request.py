from __future__ import annotations

from typing import Any

from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.translators.openai.request import openai_to_domain_request


def raw_text_to_domain_request(request: Any) -> CanonicalChatRequest:
    """Translate a raw text request to a CanonicalChatRequest."""
    if isinstance(request, str):
        return CanonicalChatRequest(
            model="text-model",
            messages=[ChatMessage(role="user", content=request)],
        )
    return openai_to_domain_request(request)
