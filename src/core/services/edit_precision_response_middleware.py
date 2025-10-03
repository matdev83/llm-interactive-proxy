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

    def __init__(self, app_state: IApplicationState) -> None:
        super().__init__(priority=10)
        self._logger = logging.getLogger(__name__)
        self._app_state = app_state
        # Load regex patterns (fallback to defaults if unavailable)
        try:
            from src.core.services.edit_precision_patterns import (
                get_response_patterns,
            )

            patterns = get_response_patterns()
        except Exception:
            patterns = [
                r"<diff_error>|diff_error",
                r"hunk\s+failed\s+to\s+apply",
                r"No\s+sufficiently\s+similar\s+match\s+found",
            ]
        self._compiled = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in patterns]

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
