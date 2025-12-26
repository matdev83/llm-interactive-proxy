"""
FastAPI request adapters.

This module contains adapters for converting FastAPI request objects
to domain-specific request contexts.
"""

from __future__ import annotations

import logging

from fastapi import Request

from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.request_context import RequestContext

logger = logging.getLogger(__name__)


def fastapi_to_domain_request_context(
    request: Request,
    attach_original: bool = False,
    domain_request: CanonicalChatRequest | None = None,
    raw_body: bytes | None = None,
) -> RequestContext:
    """Convert a FastAPI request to a domain request context.

    Args:
        request: The FastAPI request object
        attach_original: Whether to attach the original request object to the context
        domain_request: Optional canonical domain request to attach to context
        raw_body: Optional raw HTTP body bytes to attach to context

    Returns:
        A domain request context
    """
    # Extract headers
    headers = {}
    for header_name, header_value in request.headers.items():
        headers[header_name.lower()] = header_value

    # Extract cookies
    cookies = {}
    for cookie_name, cookie_value in request.cookies.items():
        cookies[cookie_name] = cookie_value

    # Try to extract agent information from headers
    agent: str | None = None
    try:
        agent = headers.get("x-agent") or headers.get("x-client-agent")
        if not agent:
            # Fall back to User-Agent; keep it concise
            ua = headers.get("user-agent")
            if ua:
                agent = ua[:80]
    except (TypeError, AttributeError):
        logger.warning("Failed to extract agent from headers", exc_info=True)
        agent = None

    # Create the context
    context = RequestContext(
        headers=headers,
        cookies=cookies,
        client_host=(
            request.client.host
            if hasattr(request, "client") and request.client
            else None
        ),
        # Adapter layer: Extract app state from FastAPI request for domain context
        # Direct access is necessary to bridge framework and domain layers
        app_state=getattr(
            request.app, "state", None
        ),  # noqa: DIP-violation-adapter-layer
        state=getattr(
            request.state, "request_state", {}
        ),  # noqa: DIP-violation-adapter-layer
        agent=agent,
        domain_request=domain_request,
        raw_body=raw_body,
    )

    # Capture original domain request for provenance tracking (Requirement 5.3)
    if domain_request is not None:
        context.capture_original_domain_request(domain_request)

    # Attach the original request if requested
    if attach_original:
        context.original_request = request

    return context
