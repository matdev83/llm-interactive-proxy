"""Interface for streaming session identifier resolution."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext


class IStreamSessionIdResolver(ABC):
    """Interface for resolving stable session identifiers for streaming.

    This interface defines the contract for determining a stable session
    identifier used for streaming capture and buffering, ensuring consistent
    identifiers across all capture/buffering code.
    """

    @abstractmethod
    def resolve_stream_session_id(
        self,
        session_id: str | None,
        context: RequestContext | None,
        request: ChatRequest | None = None,
    ) -> str:
        """Resolve stable session identifier for streaming.

        Resolution precedence (highest to lowest):
        1. session_id parameter (if provided and non-empty)
        2. request.session_id (if request provided and non-empty)
        3. request.extra_body.session_id (if request provided and non-empty)
        4. context.request_id (if context provided and non-empty)
        5. Generated UUID (fallback)

        Args:
            session_id: Explicit session ID (highest precedence)
            context: Request context containing request_id
            request: Chat request containing session_id and extra_body

        Returns:
            Stable session identifier (never empty)
        """
