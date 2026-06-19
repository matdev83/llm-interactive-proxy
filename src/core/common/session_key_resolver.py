"""Session key resolution utilities shared across core layers.

This module is transport-agnostic and can be used by services, adapters, and
other core layers without introducing core->transport import dependencies.
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
    """
    if context is None:
        return None

    request_id = context.request_id
    if not request_id or not request_id.strip():
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Cannot resolve SessionKey: request_id is missing from context",
                extra={"has_context": True},
            )
        return None

    group_id: str | None = None

    if context.headers:
        conversation_header = context.headers.get("x-conversation-id")
        if conversation_header and isinstance(conversation_header, str):
            group_id = conversation_header.strip()
            if not group_id:
                group_id = None

    if not group_id and context.domain_request is not None:
        try:
            if hasattr(context.domain_request, "conversation_id"):
                conv_id = getattr(context.domain_request, "conversation_id", None)  # type: ignore[attr-defined]
                if conv_id and isinstance(conv_id, str):
                    group_id = conv_id.strip()
                    if not group_id:
                        group_id = None
            elif hasattr(context.domain_request, "extra_body"):
                extra_body = context.domain_request.extra_body
                if isinstance(extra_body, dict):
                    conv_id = extra_body.get("conversation_id")
                    if conv_id and isinstance(conv_id, str):
                        group_id = conv_id.strip()
                        if not group_id:
                            group_id = None
        except (AttributeError, TypeError, ValueError) as exc:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to extract conversation_id from domain_request: %s",
                    exc,
                    exc_info=True,
                )

    try:
        return SessionKey(
            protocol="http",
            primary_id=request_id.strip(),
            group_id=group_id,
        )
    except ValueError as exc:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to create SessionKey from context: %s",
                exc,
                exc_info=True,
                extra={"request_id": request_id},
            )
        return None
