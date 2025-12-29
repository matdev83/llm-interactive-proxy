"""Completion session resolution collaborator."""

from __future__ import annotations

import asyncio
import logging

from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.backend_completion_collaborators import (
    ICompletionSessionResolver,
)
from src.core.interfaces.domain_entities_interface import ISession
from src.core.interfaces.session_service_interface import ISessionService

logger = logging.getLogger(__name__)


class CompletionSessionResolver(ICompletionSessionResolver):
    """Handles session lookup and per-session backend resolution."""

    def __init__(self, session_service: ISessionService):
        """Initialize the session resolver."""
        self._session_service = session_service

    async def resolve_session(
        self, context: RequestContext | None, request: CanonicalChatRequest
    ) -> tuple[ISession | None, str | None]:
        """Resolve session from context or request."""
        session: ISession | None = None
        session_id_for_backend: str | None = None

        # Resolve session from context when available
        if context and context.session_id:
            session_id_for_backend = context.session_id
            try:
                session = await self._session_service.get_session(context.session_id)
            except asyncio.CancelledError:
                # Propagate cancellation - session resolution should not block cancellation
                raise
            except (RuntimeError, ValueError, TypeError, AttributeError, KeyError) as e:
                # Catch specific exceptions from repository/service layer
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to load session '%s' for backend call: %s",
                        context.session_id,
                        e,
                        exc_info=True,
                    )
                session = None
            except Exception as e:
                # Fallback for unexpected errors - log and continue (fail-open)
                logger.warning(
                    "Unexpected error loading session '%s' for backend call: %s",
                    context.session_id,
                    e,
                    exc_info=True,
                )
                session = None

        # Try to get session from request extra_body if not found in context
        request_session_id = (
            request.extra_body.get("session_id") if request.extra_body else None
        )
        if (
            session is None
            and isinstance(request_session_id, str)
            and request_session_id
        ):
            if session_id_for_backend is None:
                session_id_for_backend = request_session_id
            try:
                session = await self._session_service.get_session(request_session_id)
            except asyncio.CancelledError:
                # Propagate cancellation - session resolution should not block cancellation
                raise
            except (RuntimeError, ValueError, TypeError, AttributeError, KeyError) as e:
                # Catch specific exceptions from repository/service layer
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Could not load session %s for backend from backend-only service: %s",
                        request_session_id,
                        e,
                        exc_info=True,
                    )
                session = None
            except Exception as e:
                # Fallback for unexpected errors - log and continue (fail-open)
                logger.warning(
                    "Unexpected error loading session %s for backend from backend-only service: %s",
                    request_session_id,
                    e,
                    exc_info=True,
                )
                session = None

        return session, session_id_for_backend
