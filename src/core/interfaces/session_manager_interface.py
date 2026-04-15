"""
Session manager interface.

This module defines the interface for session management operations.
"""

from __future__ import annotations

from typing import Protocol

from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session import Session


class ISessionManager(Protocol):
    """Interface for session management operations."""

    async def resolve_session_id(self, context: RequestContext) -> str:
        """Resolve session ID from request context."""
        ...

    async def get_session(self, session_id: str) -> Session:
        """Get session by ID."""
        ...

    async def apply_openai_codex_history_compaction_gate(
        self, session: Session, resolved_backend: str | None
    ) -> Session:
        """Disable persisted history compaction for the session when openai-codex is used.

        When the resolved backend family is ``openai-codex`` and the session still
        allows history compaction, flips ``history_compaction_allowed`` to False,
        persists the session, and emits a single warning (no per-request spam).

        Returns:
            The same ``session`` instance (mutated + persisted when applicable).
        """
        ...

    async def update_session_agent(
        self, session: Session, agent: str | None
    ) -> Session:
        """Update session agent and return updated session."""
        ...

    async def record_command_in_session(
        self, request_data: ChatRequest, session_id: str
    ) -> None:
        """Record a command-only request in the session history."""
        ...

    async def update_session_history(
        self,
        request_data: ChatRequest,
        backend_request: ChatRequest,
        backend_response: ResponseEnvelope | StreamingResponseEnvelope,
        session_id: str,
    ) -> None:
        """Update session history with the backend interaction."""
        ...
