from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Collection
from typing import Any

from src.core.domain.base_translator import BaseTranslator
from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
    CanonicalStreamChunk,
    ChatResponse,
)


class BaseFormatTranslator(BaseTranslator, ABC):
    """Abstract base class for API format translators."""

    @property
    @abstractmethod
    def format_names(self) -> Collection[str]:
        """Return the supported API format keys (including aliases)."""

    @abstractmethod
    def to_domain_request(self, request: Any) -> CanonicalChatRequest:
        """Convert API-specific request to canonical format."""

    @abstractmethod
    def to_domain_response(self, response: Any) -> CanonicalChatResponse:
        """Convert API-specific response to canonical format."""

    def from_domain_request(self, request: CanonicalChatRequest) -> dict[str, Any]:
        """Convert canonical request to API-specific format."""
        raise NotImplementedError("Translator does not support from_domain_request")

    def from_domain_response(self, response: ChatResponse) -> dict[str, Any]:
        """Convert canonical response to API-specific format."""
        raise NotImplementedError("Translator does not support from_domain_response")


class StreamingTranslatorMixin:
    """Mixin for streaming translation capabilities."""

    def to_domain_stream_chunk(
        self, chunk: Any
    ) -> dict[str, Any] | CanonicalStreamChunk:
        raise NotImplementedError("Streaming not supported")

    def from_domain_stream_chunk(self, chunk: Any) -> dict[str, Any]:
        raise NotImplementedError("Streaming not supported")
