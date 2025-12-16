"""Stub implementation of IBackendModelResolver (temporary for Phase 2).

This stub will be replaced with the actual implementation in Phase 3.
"""

from __future__ import annotations

from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.backend_model_resolver_interface import (
    IBackendModelResolver,
    ResolvedTarget,
)


class BackendModelResolverStub(IBackendModelResolver):
    """Temporary stub implementation of IBackendModelResolver.

    This stub raises NotImplementedError to ensure it's not accidentally used
    before the actual implementation is complete. It exists solely to establish
    the DI wiring during Phase 2 of the refactoring.
    """

    async def resolve_target(
        self, request: ChatRequest, context: RequestContext | None = None
    ) -> ResolvedTarget:
        """Not implemented - stub for Phase 2 DI wiring only."""
        raise NotImplementedError(
            "BackendModelResolverStub is a temporary placeholder. "
            "The actual implementation will be added in Phase 3."
        )

    def synchronize_request_with_target(
        self, request: ChatRequest, resolved: ResolvedTarget
    ) -> ChatRequest:
        """Not implemented - stub for Phase 2 DI wiring only."""
        raise NotImplementedError(
            "BackendModelResolverStub is a temporary placeholder. "
            "The actual implementation will be added in Phase 3."
        )
