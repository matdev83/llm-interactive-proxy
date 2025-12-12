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
from src.core.domain.translators.responses.request import (
    from_domain_to_responses_request,
    responses_to_domain_request,
)
from src.core.domain.translators.responses.response import (
    from_domain_to_responses_response,
    responses_to_domain_response,
)
from src.core.domain.translators.responses.streaming import (
    from_domain_to_responses_stream_chunk,
    responses_to_domain_stream_chunk,
)


class ResponsesTranslator(BaseFormatTranslator, StreamingTranslatorMixin):
    """Translator for OpenAI Responses API format."""

    @property
    def format_names(self) -> Collection[str]:
        return {"responses", "openai-responses"}

    def to_domain_request(self, request: Any) -> CanonicalChatRequest:
        return responses_to_domain_request(request)

    def from_domain_request(self, request: CanonicalChatRequest) -> dict[str, Any]:
        return from_domain_to_responses_request(request)

    def to_domain_response(self, response: Any) -> CanonicalChatResponse:
        return responses_to_domain_response(response)

    def from_domain_response(self, response: ChatResponse) -> dict[str, Any]:
        return from_domain_to_responses_response(response)

    def to_domain_stream_chunk(
        self, chunk: Any
    ) -> dict[str, Any] | CanonicalStreamChunk:
        return responses_to_domain_stream_chunk(chunk)

    def from_domain_stream_chunk(self, chunk: Any) -> dict[str, Any]:
        return from_domain_to_responses_stream_chunk(chunk)
