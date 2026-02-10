"""Interface for resolving request authentication scope identifiers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.request_context import RequestContext


class IAuthScopeResolver(ABC):
    """Resolve internal auth scope identifiers for session continuity."""

    @abstractmethod
    async def resolve_auth_scope_id(self, context: RequestContext) -> str | None:
        """Resolve auth scope for the current request.

        Returns:
            A stable auth scope identifier when available, otherwise None.
        """
