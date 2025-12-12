from __future__ import annotations

from collections.abc import Collection
from typing import Any

from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
    CanonicalStreamChunk,
)
from src.core.domain.translators.base import (
    BaseFormatTranslator,
    StreamingTranslatorMixin,
)
from src.core.domain.translators.openai.response import openai_to_domain_response
from src.core.domain.translators.openai.streaming import openai_to_domain_stream_chunk
from src.core.domain.translators.openrouter.request import openrouter_to_domain_request


class OpenRouterTranslator(BaseFormatTranslator, StreamingTranslatorMixin):
    @property
    def format_names(self) -> Collection[str]:
        return {"openrouter"}

    def to_domain_request(self, request: Any) -> CanonicalChatRequest:
        return openrouter_to_domain_request(request)

    def to_domain_response(self, response: Any) -> CanonicalChatResponse:
        return openai_to_domain_response(response)

    def to_domain_stream_chunk(
        self, chunk: Any
    ) -> dict[str, Any] | CanonicalStreamChunk:
        return openai_to_domain_stream_chunk(chunk)
