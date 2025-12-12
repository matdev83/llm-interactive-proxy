from __future__ import annotations

from collections.abc import Collection
from typing import Any

from src.core.domain.chat import CanonicalChatRequest, CanonicalChatResponse
from src.core.domain.translators.base import (
    BaseFormatTranslator,
    StreamingTranslatorMixin,
)
from src.core.domain.translators.code_assist.request import (
    code_assist_to_domain_request,
)
from src.core.domain.translators.code_assist.response import (
    code_assist_to_domain_response,
)
from src.core.domain.translators.code_assist.streaming import (
    code_assist_to_domain_stream_chunk,
)


class CodeAssistTranslator(BaseFormatTranslator, StreamingTranslatorMixin):
    @property
    def format_names(self) -> Collection[str]:
        return {"code_assist"}

    def to_domain_request(self, request: Any) -> CanonicalChatRequest:
        return code_assist_to_domain_request(request)

    def to_domain_response(self, response: Any) -> CanonicalChatResponse:
        return code_assist_to_domain_response(response)

    def to_domain_stream_chunk(self, chunk: Any) -> dict[str, Any]:
        return code_assist_to_domain_stream_chunk(chunk)
