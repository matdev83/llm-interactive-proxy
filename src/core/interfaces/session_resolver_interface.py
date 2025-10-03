"""
Interface for resolving session IDs from various sources.

This interface decouples the session ID extraction logic from the request processing,
allowing for different implementations based on the transport mechanism (HTTP, CLI, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.request_context import RequestContext


class ISessionResolver(ABC):
    """Interface for resolving session IDs from request contexts."""

    @abstractmethod
    async def resolve_session_id(self, context: RequestContext) -> str:
        """Resolve a session ID from a request context.

        This method extracts a session ID from the given context using
        implementation-specific logic, such as looking for a header,
        a cookie, a query parameter, or using a default value.

        Args:
            context: The request context to extract the session ID from

        Returns:
            The resolved session ID
        """
