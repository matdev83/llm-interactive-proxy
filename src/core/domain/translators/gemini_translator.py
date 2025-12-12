from __future__ import annotations

from collections.abc import Collection
from typing import Any

from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
    CanonicalStreamChunk,
    ChatResponse,
)
from src.core.domain.translators.base import (
    BaseFormatTranslator,
    StreamingTranslatorMixin,
)
from src.core.domain.translators.gemini.request import (
    from_domain_to_gemini_request,
    gemini_to_domain_request,
)
from src.core.domain.translators.gemini.response import (
    from_domain_to_gemini_response,
    gemini_to_domain_response,
)
from src.core.domain.translators.gemini.streaming import (
    from_domain_to_gemini_stream_chunk,
    gemini_to_domain_stream_chunk,
)


class GeminiTranslator(BaseFormatTranslator, StreamingTranslatorMixin):
    @property
    def format_names(self) -> Collection[str]:
        return {"gemini"}

    def to_domain_request(self, request: Any) -> CanonicalChatRequest:
        return gemini_to_domain_request(request)

    def from_domain_request(self, request: CanonicalChatRequest) -> dict[str, Any]:
        return from_domain_to_gemini_request(request)

    def to_domain_response(self, response: Any) -> CanonicalChatResponse:
        return gemini_to_domain_response(response)

    def from_domain_response(self, response: ChatResponse) -> dict[str, Any]:
        return from_domain_to_gemini_response(response)

    def to_domain_stream_chunk(
        self, chunk: Any
    ) -> dict[str, Any] | CanonicalStreamChunk:
        return gemini_to_domain_stream_chunk(chunk)

    def from_domain_stream_chunk(self, chunk: Any) -> dict[str, Any]:
        return from_domain_to_gemini_stream_chunk(chunk)
