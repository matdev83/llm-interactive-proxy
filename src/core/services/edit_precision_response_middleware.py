from __future__ import annotations

import logging
import re
from typing import Any

from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    ProcessedResponse,
)


class EditPrecisionResponseMiddleware(IResponseMiddleware):
    """Detects edit failures in model responses and flags next-call tuning.

    If a response contains known edit-failure markers (e.g., diff_error), this
    middleware marks the current session to apply edit-precision overrides on the
    next outbound request.
    """

    # Pre-compiled regex patterns for performance optimization
    # These patterns are compiled once at class definition time instead of on every instantiation
    _DEFAULT_PATTERNS = [
        re.compile(r"<diff_error>|diff_error", re.IGNORECASE | re.DOTALL),
        re.compile(r"hunk\s+failed\s+to\s+apply", re.IGNORECASE | re.DOTALL),
        re.compile(
            r"No\s+sufficiently\s+similar\s+match\s+found", re.IGNORECASE | re.DOTALL
        ),
    ]

    def __init__(self, app_state: IApplicationState) -> None:
        super().__init__(priority=10)
        self._logger = logging.getLogger(__name__)
        self._app_state = app_state

        # Start with pre-compiled default patterns for performance
        self._compiled = list(self._DEFAULT_PATTERNS)

        # Load additional patterns from external config if available
        try:
            from src.core.services.edit_precision_patterns import (
                get_response_patterns,
            )

            config_patterns = get_response_patterns()
            # Only compile patterns that aren't already in defaults
            default_pattern_strings = {
                r"<diff_error>|diff_error",
                r"hunk\s+failed\s+to\s+apply",
                r"No\s+sufficiently\s+similar\s+match\s+found",
            }
            for pattern in config_patterns:
                if pattern not in default_pattern_strings:
                    self._compiled.append(
                        re.compile(pattern, re.IGNORECASE | re.DOTALL)
                    )
        except Exception:
            # Use only default patterns if config loading fails
            pass

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        # Normalize to ProcessedResponse for chaining
        if isinstance(response, ProcessedResponse):
            text = response.content or ""
            out = response
        else:
            text = str(response) if response is not None else ""
            out = ProcessedResponse(content=text)

        if not text:
            return out

        matched_pattern: str | None = None
        for p in self._compiled:
            try:
                if p.search(text):
                    matched_pattern = getattr(p, "pattern", None) or str(p)
                    break
            except Exception:
                continue

        if matched_pattern is not None:
            # Set pending flag for this session (one-shot)
            pending_map = self._app_state.get_setting("edit_precision_pending", {})
            try:
                # Expect a dict[str, int]
                if not isinstance(pending_map, dict):
                    pending_map = {}
            except Exception:
                pending_map = {}

            key = session_id or ""
            if key:
                pending_map[key] = int(pending_map.get(key, 0)) + 1
                self._app_state.set_setting("edit_precision_pending", pending_map)
                # Best-effort logging; do not let logging failures affect flow
                try:
                    response_type = (
                        str((context or {}).get("response_type")) if context else ""
                    )
                    self._logger.info(
                        "Edit-precision trigger detected; session_id=%s pattern=%s count=%s response_type=%s",
                        key,
                        matched_pattern,
                        pending_map.get(key, 0),
                        response_type,
                    )
                except Exception as e:
                    self._logger.debug(
                        "Error logging edit-precision trigger: %s", e, exc_info=True
                    )
        return out
