"""Shared frontend session-resolution helpers."""

from __future__ import annotations

import logging
from typing import cast

from src.core.domain.request_context import RequestContext
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.session_manager_interface import ISessionManager

logger = logging.getLogger(__name__)


async def resolve_session_before_capture(
    *,
    service_provider: IServiceProvider | None,
    context: RequestContext,
) -> str | None:
    """Resolve canonical session id before inbound wire-capture metadata."""
    if service_provider is None:
        return context.session_id

    try:
        session_manager = service_provider.get_service(cast(type, ISessionManager))
    except Exception as exc:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Failed to resolve session manager before capture: %s",
                exc,
                exc_info=True,
            )
        return context.session_id

    if session_manager is None:
        return context.session_id

    try:
        resolved_session_id = await session_manager.resolve_session_id(context)
    except Exception as exc:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Failed to resolve session id before capture: %s",
                exc,
                exc_info=True,
            )
        return context.session_id

    if isinstance(resolved_session_id, str) and resolved_session_id:
        context.session_id = resolved_session_id
    return context.session_id
