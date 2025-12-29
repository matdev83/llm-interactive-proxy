"""
Translator protocol definitions.

These protocols define the contract for format-specific translation components.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any, Protocol, runtime_checkable

from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
    CanonicalStreamChunk,
    ChatResponse,
)


@runtime_checkable
class TranslatorProtocol(Protocol):
    """Protocol defining the contract for API format translators."""

    @property
    def format_names(self) -> Collection[str]:
        """Supported format keys, including any aliases."""
        ...

    def to_domain_request(self, request: Any) -> CanonicalChatRequest:
        """Convert API-specific request to canonical format."""
        ...

    def from_domain_request(self, request: CanonicalChatRequest) -> dict[str, Any]:
        """Convert canonical request to API-specific format."""
        ...

    def to_domain_response(self, response: Any) -> CanonicalChatResponse:
        """Convert API-specific response to canonical format."""
        ...

    def from_domain_response(self, response: ChatResponse) -> dict[str, Any]:
        """Convert canonical response to API-specific format."""
        ...


@runtime_checkable
class StreamingTranslatorProtocol(Protocol):
    """Protocol for streaming chunk translation."""

    def to_domain_stream_chunk(
        self, chunk: Any
    ) -> dict[str, Any] | CanonicalStreamChunk:
        """Convert API-specific stream chunk to canonical format."""
        ...

    def from_domain_stream_chunk(self, chunk: Any) -> dict[str, Any]:
        """Convert canonical stream chunk to API-specific format."""
        ...
