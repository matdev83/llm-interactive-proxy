"""Stub implementation of IStreamSessionIdResolver (temporary for Phase 2).

This stub will be replaced with the actual implementation in Phase 3.
"""

from __future__ import annotations

from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.stream_session_id_resolver_interface import (
    IStreamSessionIdResolver,
)


class StreamSessionIdResolverStub(IStreamSessionIdResolver):
    """Temporary stub implementation of IStreamSessionIdResolver.

    This stub raises NotImplementedError to ensure it's not accidentally used
    before the actual implementation is complete. It exists solely to establish
    the DI wiring during Phase 2 of the refactoring.
    """

    def resolve_stream_session_id(
        self,
        session_id: str | None,
        context: RequestContext | None,
        request: ChatRequest | None = None,
    ) -> str:
        """Not implemented - stub for Phase 2 DI wiring only."""
        raise NotImplementedError(
            "StreamSessionIdResolverStub is a temporary placeholder. "
            "The actual implementation will be added in Phase 3."
        )
