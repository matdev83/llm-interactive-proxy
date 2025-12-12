from __future__ import annotations

from collections.abc import Collection
from typing import Any

from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
    ChatResponse,
)
from src.core.domain.translators.anthropic.request import (
    anthropic_to_domain_request,
    from_domain_to_anthropic_request,
)
from src.core.domain.translators.anthropic.response import (
    anthropic_to_domain_response,
    from_domain_to_anthropic_response,
)
from src.core.domain.translators.anthropic.streaming import (
    anthropic_to_domain_stream_chunk,
    from_domain_to_anthropic_stream_chunk,
)
from src.core.domain.translators.base import (
    BaseFormatTranslator,
    StreamingTranslatorMixin,
)


class AnthropicTranslator(BaseFormatTranslator, StreamingTranslatorMixin):
    @property
    def format_names(self) -> Collection[str]:
        return {"anthropic"}

    def to_domain_request(self, request: Any) -> CanonicalChatRequest:
        return anthropic_to_domain_request(request)

    def from_domain_request(self, request: CanonicalChatRequest) -> dict[str, Any]:
        return from_domain_to_anthropic_request(request)

    def to_domain_response(self, response: Any) -> CanonicalChatResponse:
        return anthropic_to_domain_response(response)

    def from_domain_response(self, response: ChatResponse) -> dict[str, Any]:
        return from_domain_to_anthropic_response(response)

    def to_domain_stream_chunk(self, chunk: Any) -> dict[str, Any]:
        return anthropic_to_domain_stream_chunk(chunk)

    def from_domain_stream_chunk(self, chunk: Any) -> dict[str, Any]:
        return from_domain_to_anthropic_stream_chunk(chunk)
