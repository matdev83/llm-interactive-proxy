"""Fingerprint request transformation helpers.

These helpers apply proxy-side mutations that should be accounted for when
computing session fingerprints so matching uses the same content representation.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.configuration_interface import IConfig

logger = logging.getLogger(__name__)


def _resolve_config(
    *, context: RequestContext | None, config: IConfig | None
) -> IConfig | None:
    if config is not None:
        return config

    if context is None:
        return None

    try:
        app_state = getattr(context, "app_state", None)
        if app_state is None:
            return None
        value: Any = app_state.get_setting("app_config")
        return cast(IConfig | None, value)
    except (AttributeError, KeyError, TypeError):
        return None


def _should_redact_api_keys(config: IConfig | None) -> bool:
    if config is None:
        return True
    try:
        auth = getattr(config, "auth", None)
        if auth is None:
            return True
        return bool(getattr(auth, "redact_api_keys_in_prompts", True))
    except (AttributeError, TypeError, ValueError):
        return True


async def apply_fingerprint_transforms(
    request: ChatRequest,
    *,
    context: RequestContext | None = None,
    config: IConfig | None = None,
    session_id: str | None = None,
) -> ChatRequest:
    """Apply request mutations that affect fingerprinting."""
    effective_config = _resolve_config(context=context, config=config)
    if not _should_redact_api_keys(effective_config):
        return request

    try:
        from src.core.common.logging_utils import (
            discover_api_keys_from_config_and_env,
        )
        from src.core.services.redaction_middleware import RedactionMiddleware

        config_for_redaction = cast(AppConfig | None, effective_config)
        api_keys = discover_api_keys_from_config_and_env(config_for_redaction)
        redaction = RedactionMiddleware(api_keys=api_keys)

        redaction_context: dict[str, Any] = {}
        if session_id:
            redaction_context["session_id"] = session_id

        return await redaction.process(request, redaction_context)
    except Exception as exc:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Fingerprint redaction failed; using original request content: %s",
                exc,
                exc_info=True,
            )
        return request
