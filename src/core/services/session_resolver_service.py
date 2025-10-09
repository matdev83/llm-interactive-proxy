"""
Implementation of the session resolver interface.

This module provides implementations for resolving session IDs from different sources,
including HTTP headers, cookies, and configuration settings.
"""

from __future__ import annotations

import logging
import uuid

from src.core.domain.request_context import RequestContext
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.session_resolver_interface import ISessionResolver

logger = logging.getLogger(__name__)


class DefaultSessionResolver(ISessionResolver):
    """Default implementation of the session resolver interface.

    This implementation tries to resolve a session ID from:
    1. The request's session_id attribute (if present)
    2. The x-session-id header
    3. A fallback default value (configurable)
    """

    def __init__(self, config: IConfig | None = None) -> None:
        """Initialize the session resolver.

        Args:
            config: Optional configuration object
        """
        self.config = config
        self._configured_default_session_id: str | None = None

        # Try to get a configured default session ID if available
        if config is not None:
            try:
                if hasattr(config, "session") and hasattr(
                    config.session, "default_session_id"
                ):
                    configured_default: str | None = config.session.default_session_id
                    if configured_default:
                        self._configured_default_session_id = configured_default
            except (AttributeError, TypeError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Could not read default session ID from config: {e}")

    @staticmethod
    def _generate_session_id() -> str:
        """Generate a new random session ID for anonymous requests."""

        return str(uuid.uuid4())

    async def resolve_session_id(self, context: RequestContext) -> str:
        """Resolve a session ID from a request context.

        Args:
            context: The request context to extract the session ID from

        Returns:
            The resolved session ID
        """
        session_id: str | None = None

        # Try to get session ID from domain request attached to context if available
        if hasattr(context, "domain_request"):
            from src.core.domain.chat import ChatRequest

            domain_request = getattr(context, "domain_request", None)
            if domain_request is not None and isinstance(domain_request, ChatRequest):
                session_id = domain_request.session_id
                if not session_id:
                    # Fallback: some clients pass session_id via extra_body
                    try:
                        extra = getattr(domain_request, "extra_body", None)
                        if isinstance(extra, dict):
                            eb_sid = extra.get("session_id")
                            if isinstance(eb_sid, str) and eb_sid:
                                session_id = eb_sid
                    except Exception:
                        session_id = None

        if not session_id:
            # Try to get session ID from context attribute populated by adapters/middleware
            ctx_session_id = getattr(context, "session_id", None)
            if isinstance(ctx_session_id, str) and ctx_session_id:
                session_id = ctx_session_id

        if not session_id:
            # Try to get session ID from headers
            header_value = context.headers.get("x-session-id")
            if isinstance(header_value, str) and header_value:
                session_id = header_value

        if not session_id:
            # Try to get session ID from cookies
            cookie_value = context.cookies.get("session_id")
            if isinstance(cookie_value, str) and cookie_value:
                session_id = cookie_value

        if not session_id:
            # Fall back to configured default or generate a new session ID per request
            session_id = self._configured_default_session_id or self._generate_session_id()
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Generated new session_id '%s' due to missing identifiers", session_id
                )

        self._set_context_session_id(context, session_id)
        return session_id

    @staticmethod
    def _set_context_session_id(context: RequestContext, session_id: str) -> None:
        """Attach the resolved session ID back to the request context if possible."""

        try:
            context.session_id = session_id
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Unable to set session_id on context", exc_info=True)
