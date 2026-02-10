"""Interface for extracting untrusted client session identifiers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.request_context import RequestContext


class IClientSessionIdExtractor(ABC):
    """Extract client-provided session identifier metadata from request context."""

    @abstractmethod
    def extract_client_session_id(self, context: RequestContext) -> str | None:
        """Extract untrusted client session identifier metadata."""
