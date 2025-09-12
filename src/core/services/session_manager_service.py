"""
Session manager implementation.

This module provides the implementation of the session manager interface.
"""

from __future__ import annotations

# mypy: disable-error-code="unreachable"
import logging

from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session import Session, SessionInteraction
from src.core.interfaces.session_manager_interface import ISessionManager
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.interfaces.session_service_interface import ISessionService

logger = logging.getLogger(__name__)


class SessionManager(ISessionManager):
    """Implementation of the session manager."""

    def __init__(
        self,
        session_service: ISessionService,
        session_resolver: ISessionResolver,
    ) -> None:
        """Initialize the session manager."""
        self._session_service = session_service
        self._session_resolver = session_resolver

    async def resolve_session_id(self, context: RequestContext) -> str:
        """Resolve session ID from request context."""
        return await self._session_resolver.resolve_session_id(context)

    async def get_session(self, session_id: str) -> Session:
        """Get session by ID."""
        return await self._session_service.get_session(session_id)

    async def update_session_agent(
        self, session: Session, agent: str | None
    ) -> Session:
        """Update session agent and return updated session."""
        if agent is not None and agent != session.agent:
            logger.debug(f"Setting session agent from request_data: {agent}")
            session.agent = agent
            await self._session_service.update_session(session)
            # Re-fetch to ensure latest state
            session = await self._session_service.get_session(session.id)
            logger.debug(f"Session object ID after re-fetch: {id(session)}")
        return session

    async def record_command_in_session(
        self, request_data: ChatRequest, session_id: str
    ) -> None:
        """Record a command-only request in the session history."""
        session = await self._session_service.get_session(session_id)

        def _extract_role_and_content(
            message: object,
        ) -> tuple[str | None, object | None]:
            """Best-effort extraction of role/content from heterogeneous message types."""
            # Use Any internally to avoid mypy complaints on duck-typed access
            from typing import Any, cast

            msg_any = cast(Any, message)
            # Pydantic models expose model_dump
            if hasattr(msg_any, "model_dump") and callable(msg_any.model_dump):
                try:
                    data = msg_any.model_dump()
                    return data.get("role"), data.get("content")
                except Exception:
                    pass
            # Mapping-like messages
            if isinstance(msg_any, dict):
                return msg_any.get("role"), msg_any.get("content")
            # Fallback to attribute access
            return getattr(msg_any, "role", None), getattr(msg_any, "content", None)

        raw_prompt = ""
        if request_data and getattr(request_data, "messages", None):
            for message in reversed(request_data.messages):
                role, content = _extract_role_and_content(message)
                if role == "user":
                    raw_prompt = content if isinstance(content, str) else str(content)
                    break

        if raw_prompt:
            try:
                last = session.history[-1] if session.history else None
                last_prompt = getattr(last, "prompt", None) if last else None
            except (IndexError, AttributeError) as e:
                logger.warning(
                    f"Could not retrieve last prompt from session history: {e}",
                    exc_info=True,
                )
                last_prompt = None

            if last_prompt != raw_prompt:
                session.add_interaction(
                    SessionInteraction(
                        prompt=raw_prompt,
                        handler="proxy",
                        backend=getattr(
                            session.state.backend_config, "backend_type", None
                        ),
                        model=getattr(session.state.backend_config, "model", None),
                        project=getattr(session.state, "project", None),
                        parameters={
                            "temperature": getattr(request_data, "temperature", None),
                            "top_p": getattr(request_data, "top_p", None),
                            "max_tokens": getattr(request_data, "max_tokens", None),
                        },
                    )
                )
                await self._session_service.update_session(session)

    async def update_session_history(
        self,
        request_data: ChatRequest,
        backend_request: ChatRequest,
        backend_response: ResponseEnvelope | StreamingResponseEnvelope,
        session_id: str,
    ) -> None:
        """Update session history with the backend interaction."""
        # BackendProcessor records backend interactions; avoid duplicating entries here.
        # This method is retained for compatibility and future extensions.
        _ = await self._session_service.get_session(session_id)
