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
from src.core.domain.translators.openai.request import (
    from_domain_to_openai_request,
    openai_to_domain_request,
)
from src.core.domain.translators.openai.response import (
    from_domain_to_openai_response,
    openai_to_domain_response,
)
from src.core.domain.translators.openai.streaming import (
    from_domain_to_openai_stream_chunk,
    openai_to_domain_stream_chunk,
)


class OpenAITranslator(BaseFormatTranslator, StreamingTranslatorMixin):
    @property
    def format_names(self) -> Collection[str]:
        return {"openai"}

    def to_domain_request(self, request: Any) -> CanonicalChatRequest:
        return openai_to_domain_request(request)

    def from_domain_request(self, request: CanonicalChatRequest) -> dict[str, Any]:
        return from_domain_to_openai_request(request)

    def to_domain_response(self, response: Any) -> CanonicalChatResponse:
        return openai_to_domain_response(response)

    def from_domain_response(self, response: ChatResponse) -> dict[str, Any]:
        return from_domain_to_openai_response(response)

    def to_domain_stream_chunk(
        self, chunk: Any
    ) -> dict[str, Any] | CanonicalStreamChunk:
        return openai_to_domain_stream_chunk(chunk)

    def from_domain_stream_chunk(self, chunk: Any) -> dict[str, Any]:
        return from_domain_to_openai_stream_chunk(chunk)
