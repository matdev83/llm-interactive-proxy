"""
Implementation of the session resolver interface.

This module provides implementations for resolving session IDs from different sources,
including HTTP headers, cookies, and configuration settings.
"""

from __future__ import annotations

import logging

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
        self.default_session_id = "default"

        # Try to get a configured default session ID if available
        if config is not None:
            try:
                # Check if a default session ID is configured
                if hasattr(config, "session") and hasattr(
                    config.session, "default_session_id"
                ):
                    configured_default: str | None = config.session.default_session_id
                    if configured_default:
                        self.default_session_id = configured_default
            except (AttributeError, TypeError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Could not read default session ID from config: {e}")

    async def resolve_session_id(self, context: RequestContext) -> str:
        """Resolve a session ID from a request context.

        Args:
            context: The request context to extract the session ID from

        Returns:
            The resolved session ID
        """
        # Try to get session ID from domain request attached to context if available
        if hasattr(context, "domain_request"):
            from src.core.domain.chat import ChatRequest

            domain_request = getattr(context, "domain_request", None)
            if domain_request is not None and isinstance(domain_request, ChatRequest):
                session_id: str | None = domain_request.session_id
                if session_id:
                    return session_id
                # Fallback: some clients pass session_id via extra_body
                try:
                    extra = getattr(domain_request, "extra_body", None)
                    if isinstance(extra, dict):
                        eb_sid = extra.get("session_id")
                        if isinstance(eb_sid, str) and eb_sid:
                            return eb_sid
                except Exception:
                    pass

        # Try to get session ID from headers
        header_value = context.headers.get("x-session-id")
        if header_value is not None and isinstance(header_value, str):
            return header_value

        # Try to get session ID from cookies
        cookie_value = context.cookies.get("session_id")
        if cookie_value is not None and isinstance(cookie_value, str):
            return cookie_value

        # Fall back to default session ID
        return self.default_session_id
