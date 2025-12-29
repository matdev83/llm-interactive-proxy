"""Stream session ID resolver service.

This service provides a centralized, consistent algorithm for resolving
stable session identifiers used in streaming capture and buffering.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.stream_session_id_resolver_interface import (
    IStreamSessionIdResolver,
)

logger = logging.getLogger(__name__)


class StreamSessionIdResolver(IStreamSessionIdResolver):
    """Unified resolver for streaming session identifiers.

    This implementation consolidates the previously duplicated session ID
    resolution logic from BackendService and BufferedWireCapture into a
    single, consistent algorithm.

    Resolution precedence (highest to lowest):
    1. session_id parameter (explicit override)
    2. request.session_id (request-level identifier)
    3. request.extra_body.session_id (metadata fallback)
    4. context.request_id (request context identifier)
    5. Generated UUID (ultimate fallback)
    """

    def resolve_stream_session_id(
        self,
        session_id: str | None,
        context: RequestContext | None,
        request: ChatRequest | None = None,
    ) -> str:
        """Resolve stable session identifier for streaming.

        Args:
            session_id: Explicit session ID (highest precedence)
            context: Request context containing request_id
            request: Chat request containing session_id and extra_body

        Returns:
            Stable session identifier (never empty)
        """
        # Precedence 1: Explicit session_id parameter
        if session_id:
            return str(session_id)

        # Precedence 2: request.session_id
        if request is not None:
            request_session = getattr(request, "session_id", None)
            if request_session:
                return str(request_session)

        # Precedence 3: request.extra_body.session_id
        if request is not None:
            try:
                extra_body = getattr(request, "extra_body", None)
                if isinstance(extra_body, dict):
                    extra_session = extra_body.get("session_id")
                    if extra_session:
                        return str(extra_session)
            except (AttributeError, TypeError):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to read session_id from request.extra_body",
                        exc_info=True,
                    )

        # Precedence 4: context.request_id
        if context is not None:
            context_request_id = getattr(context, "request_id", None)
            if context_request_id:
                return str(context_request_id)

        # Precedence 5: Generate UUID fallback
        return uuid4().hex
