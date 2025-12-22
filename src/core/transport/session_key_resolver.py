"""Session key resolution utilities for transport layers.

This module provides utilities for resolving SessionKey from transport-specific
contexts (HTTP RequestContext, Codebuff connection state, etc.).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.domain.session_key import SessionKey

if TYPE_CHECKING:
    from src.core.domain.request_context import RequestContext

logger = logging.getLogger(__name__)


def resolve_session_key_from_request_context(
    context: RequestContext | None,
) -> SessionKey | None:
    """Resolve SessionKey from HTTP RequestContext.

    This function extracts the lifecycle session identity from a RequestContext
    for use in cancellation and End-of-Session scoping.

    Mapping rules (per design.md):
    - protocol: "http"
    - primary_id: context.request_id (Trace ID - required)
    - group_id: conversation_id from headers (x-conversation-id) or body (optional)

    Args:
        context: Request context containing request_id and headers

    Returns:
        SessionKey if request_id is available, None otherwise.
        Returns None if request_id is missing (enforces "missing context => no attribution").

    Example:
        >>> context = RequestContext(
        ...     headers={"x-conversation-id": "conv-123"},
        ...     request_id="trace-abc",
        ...     ...
        ... )
        >>> key = resolve_session_key_from_request_context(context)
        >>> assert key == SessionKey(
        ...     protocol="http",
        ...     primary_id="trace-abc",
        ...     group_id="conv-123"
        ... )
    """
    if context is None:
        return None

    # Requirement 1.6: primary_id is required - no attribution without request_id
    request_id = context.request_id
    if not request_id or not request_id.strip():
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Cannot resolve SessionKey: request_id is missing from context",
                extra={"has_context": True},
            )
        return None

    # Extract conversation_id from headers (x-conversation-id) or body
    group_id: str | None = None

    # Try headers first
    if context.headers:
        conversation_header = context.headers.get("x-conversation-id")
        if conversation_header and isinstance(conversation_header, str):
            group_id = conversation_header.strip()
            if not group_id:
                group_id = None

    # Try body/domain_request if header not found
    if not group_id and context.domain_request is not None:
        try:
            # Check if domain_request has conversation_id attribute
            if hasattr(context.domain_request, "conversation_id"):
                conv_id = context.domain_request.conversation_id
                if conv_id and isinstance(conv_id, str):
                    group_id = conv_id.strip()
                    if not group_id:
                        group_id = None
            # Also check extra_body for conversation_id
            elif hasattr(context.domain_request, "extra_body"):
                extra_body = context.domain_request.extra_body
                if isinstance(extra_body, dict):
                    conv_id = extra_body.get("conversation_id")
                    if conv_id and isinstance(conv_id, str):
                        group_id = conv_id.strip()
                        if not group_id:
                            group_id = None
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to extract conversation_id from domain_request: %s",
                    e,
                    exc_info=True,
                )

    try:
        return SessionKey(
            protocol="http",
            primary_id=request_id.strip(),
            group_id=group_id,
        )
    except ValueError as e:
        # SessionKey validation failed (e.g., empty primary_id after strip)
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to create SessionKey from context: %s",
                e,
                extra={"request_id": request_id},
            )
        return None


def create_codebuff_session_key(client_session_id: str) -> SessionKey:
    """Create SessionKey for Codebuff WebSocket session.

    Args:
        client_session_id: The client-provided session ID from identify message

    Returns:
        SessionKey with protocol="codebuff" and primary_id="codebuff:{client_session_id}"

    Raises:
        ValueError: If client_session_id is empty or invalid
    """
    if not client_session_id or not client_session_id.strip():
        raise ValueError("client_session_id cannot be empty")

    return SessionKey(
        protocol="codebuff",
        primary_id=f"codebuff:{client_session_id.strip()}",
        group_id=None,  # Codebuff doesn't use group_id (1:1 connection)
    )
