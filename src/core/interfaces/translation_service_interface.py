"""
Translation service interface.

This module defines the interface for translation services.
"""

from typing import Any, Protocol

from src.core.domain.chat import CanonicalChatRequest


class ITranslationService(Protocol):
    """Interface for translation services."""

    def to_domain_request(
        self, request: Any, source_format: str
    ) -> CanonicalChatRequest:
        """
        Translates an incoming request from a specific API format to the internal domain ChatRequest.

        Args:
            request: The request object in the source format.
            source_format: The source API format (e.g., "anthropic", "gemini").

        Returns:
            A ChatRequest object.
        """
        ...

    def from_domain_request(
        self, request: CanonicalChatRequest, target_format: str
    ) -> Any:
        """
        Translates an internal domain ChatRequest to a specific API format.

        Args:
            request: The internal ChatRequest object.
            target_format: The target API format (e.g., "anthropic", "gemini").

        Returns:
            The request object in the target format.
        """
        ...

    def to_domain_response(self, response: Any, source_format: str) -> Any:
        """
        Translates a response from a specific API format to the internal domain format.

        Args:
            response: The response object in the source format.
            source_format: The source API format (e.g., "anthropic", "gemini").

        Returns:
            The response object in the internal domain format.
        """
        ...

    def from_domain_response(self, response: Any, target_format: str) -> Any:
        """
        Translates an internal domain response to a specific API format.

        Args:
            response: The internal domain response object.
            target_format: The target API format (e.g., "anthropic", "gemini").

        Returns:
            The response object in the target format.
        """
        ...
