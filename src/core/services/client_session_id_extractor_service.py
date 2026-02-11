"""Client session identifier extraction with strict trust-boundary rules."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Final

from src.core.domain.request_context import RequestContext
from src.core.interfaces.client_session_id_extractor_interface import (
    IClientSessionIdExtractor,
)
from src.core.interfaces.configuration_interface import IConfig

logger = logging.getLogger(__name__)

_DEFAULT_ECHO_HEADER: Final[str] = "x-b2bua-session-id"


class DefaultClientSessionIdExtractor(IClientSessionIdExtractor):
    """Extract client session id as untrusted metadata only."""

    def __init__(self, config: IConfig | None = None) -> None:
        self._config = config
        self._configured_echo_header_name = self._resolve_configured_echo_header_name()

    def extract_client_session_id(self, context: RequestContext) -> str | None:
        """Extract client session id using precedence rules and conflict diagnostics."""
        header_candidate = self._extract_header_candidate(context)
        body_candidate, extra_body_candidate = self._extract_body_candidates(context)

        candidates = {
            "header": header_candidate,
            "body": body_candidate,
            "extra_body": extra_body_candidate,
        }

        self._record_conflict_diagnostic_if_needed(context, candidates)

        extracted = header_candidate or body_candidate or extra_body_candidate or None
        if extracted is not None:
            context.ensure_processing_context().update(
                {"b2bua_client_session_id": extracted}
            )

        return extracted

    def _resolve_configured_echo_header_name(self) -> str:
        if self._config is None:
            return _DEFAULT_ECHO_HEADER

        try:
            session_cfg = getattr(self._config, "session", None)
            b2bua_cfg = getattr(session_cfg, "b2bua", None)
            configured = getattr(b2bua_cfg, "echo_header_name", None)
            if isinstance(configured, str):
                normalized = configured.strip().lower()
                if normalized:
                    return normalized
        except (AttributeError, TypeError):
            return _DEFAULT_ECHO_HEADER

        return _DEFAULT_ECHO_HEADER

    def _extract_header_candidate(self, context: RequestContext) -> str | None:
        # If operators configure echo header name to x-session-id, inbound x-session-id
        # must still be ignored for identity to prevent trust-boundary confusion.
        if self._configured_echo_header_name == "x-session-id":
            return None

        return self._normalize_candidate(context.get_header("x-session-id"))

    @staticmethod
    def _extract_body_candidates(
        context: RequestContext,
    ) -> tuple[str | None, str | None]:
        body_candidate: str | None = None
        extra_body_candidate: str | None = None

        domain_request = context.domain_request
        if domain_request is None:
            return body_candidate, extra_body_candidate

        body_candidate = DefaultClientSessionIdExtractor._normalize_candidate(
            getattr(domain_request, "session_id", None)
        )

        extra_body = getattr(domain_request, "extra_body", None)
        if isinstance(extra_body, Mapping):
            extra_body_candidate = DefaultClientSessionIdExtractor._normalize_candidate(
                extra_body.get("session_id")
            )

        return body_candidate, extra_body_candidate

    @staticmethod
    def _normalize_candidate(value: Any) -> str | None:
        if not isinstance(value, str):
            return None

        normalized = value.strip()
        if not normalized:
            return None

        return normalized

    @staticmethod
    def _record_conflict_diagnostic_if_needed(
        context: RequestContext,
        candidates: Mapping[str, str | None],
    ) -> None:
        present_values = [value for value in candidates.values() if value is not None]
        if len(set(present_values)) <= 1:
            return

        context.ensure_processing_context().update(
            {"b2bua_client_session_id_conflict": True}
        )

        if logger.isEnabledFor(logging.WARNING):
            conflicting_sources = [
                source for source, value in candidates.items() if value is not None
            ]
            logger.warning(
                "Conflicting client session identifiers detected from sources=%s; "
                "using precedence header > body > extra_body",
                conflicting_sources,
            )
