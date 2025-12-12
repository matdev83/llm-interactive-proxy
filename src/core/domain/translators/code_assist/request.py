from __future__ import annotations

from typing import Any

from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.translators.openai.request import openai_to_domain_request


def code_assist_to_domain_request(request: Any) -> CanonicalChatRequest:
    """
    Translate a Code Assist API request to a CanonicalChatRequest.

    The Code Assist API uses the same format as OpenAI for the core request,
    but with additional project field and different endpoint.
    """
    if isinstance(request, dict):
        cleaned_request = {k: v for k, v in request.items() if k != "project"}
        return openai_to_domain_request(cleaned_request)

    return openai_to_domain_request(request)
