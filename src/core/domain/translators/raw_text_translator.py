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
from src.core.domain.translators.raw_text.request import raw_text_to_domain_request
from src.core.domain.translators.raw_text.response import raw_text_to_domain_response
from src.core.domain.translators.raw_text.streaming import (
    raw_text_to_domain_stream_chunk,
)


class RawTextTranslator(BaseFormatTranslator, StreamingTranslatorMixin):
    @property
    def format_names(self) -> Collection[str]:
        return {"raw_text"}

    def to_domain_request(self, request: Any) -> CanonicalChatRequest:
        return raw_text_to_domain_request(request)

    def to_domain_response(self, response: Any) -> CanonicalChatResponse:
        return raw_text_to_domain_response(response)

    def to_domain_stream_chunk(
        self, chunk: Any
    ) -> dict[str, Any] | CanonicalStreamChunk:
        return raw_text_to_domain_stream_chunk(chunk)
