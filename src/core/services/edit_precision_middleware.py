"""
Edit-precision tuning middleware for the request pipeline.

Detects agent prompts that indicate a failed file-edit attempt (e.g.,
SEARCH/REPLACE mismatches, multiple matches, or unified diff hunk failures)
and temporarily lowers sampling parameters (temperature/top_p) for the
current single request to improve precision of the next model response.

This middleware is transport- and backend-agnostic and operates purely on the
ChatRequest, so no individual backend connector changes are needed.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import Any

from src.core.config.edit_precision_temperatures import (
    EditPrecisionTemperaturesConfig,
)
from src.core.domain.chat import ChatRequest
from src.core.interfaces.request_processor_interface import IRequestMiddleware


class EditPrecisionTuningMiddleware(IRequestMiddleware):
    """Request middleware to tune model parameters for precision.

    - Scans request messages for known agent edit-failure prompts
    - If detected, lowers temperature (and optionally top_p) for this request only
    """

    def __init__(
        self,
        *,
        target_temperature: float = 0.1,
        min_top_p: float | None = 0.3,
        extra_patterns: Iterable[str] | None = None,
        force_apply: bool = False,
        temperatures_config: EditPrecisionTemperaturesConfig | None = None,
    ) -> None:
        self._target_temperature = max(0.0, float(target_temperature))
        self._min_top_p = None if min_top_p is None else max(0.0, float(min_top_p))
        self._force_apply = force_apply
        self._logger = logging.getLogger(__name__)
        # Optional target top_k may be injected via context in RequestProcessor; default None here
        self._target_top_k: int | None = None
        # Model-specific temperatures configuration
        self._temperatures_config = (
            temperatures_config or EditPrecisionTemperaturesConfig()
        )

        # Load patterns from configuration file if present, otherwise use defaults
        try:
            from src.core.services.edit_precision_patterns import (
                get_request_patterns,
            )

            base_patterns: list[str] = get_request_patterns()
        except Exception:
            base_patterns = []

        if extra_patterns:
            base_patterns.extend(list(extra_patterns))

        self._compiled = [
            re.compile(p, re.IGNORECASE | re.DOTALL) for p in base_patterns
        ]

    async def process(
        self, request: ChatRequest, context: dict[str, Any] | None = None
    ) -> ChatRequest:
        """Process a ChatRequest and apply precision tuning if edit-failure prompts are detected."""
        if not request or not request.messages:
            return request

        if not self._force_apply and not self._contains_edit_failure_prompt(request):
            return request

        # Clone request and apply conservative precision overrides for this call only
        new_temperature = self._compute_temperature(request.temperature, request.model)
        new_top_p = self._compute_top_p(request.top_p)
        new_top_k = self._compute_top_k(getattr(request, "top_k", None))

        extra_body = dict(request.extra_body or {})
        extra_body.setdefault("_edit_precision_mode", True)
        if "_edit_precision_meta" not in extra_body:
            extra_body["_edit_precision_meta"] = {}
        extra_body["_edit_precision_meta"].update(
            {
                "original_temperature": request.temperature,
                "original_top_p": request.top_p,
                "original_top_k": getattr(request, "top_k", None),
                "applied_temperature": new_temperature,
                "applied_top_p": new_top_p,
                "applied_top_k": new_top_k,
            }
        )

        # Best-effort logging; do not let logging failures affect flow
        try:
            session_id = ""
            if context and isinstance(context, dict):
                session_id = str(context.get("session_id", ""))
            self._logger.info(
                "Edit-precision overrides applied; session_id=%s force_apply=%s temp:%s->%s top_p:%s->%s top_k:%s->%s one_shot=True",
                session_id,
                bool(self._force_apply),
                request.temperature,
                new_temperature,
                request.top_p,
                new_top_p,
                getattr(request, "top_k", None),
                new_top_k,
            )
        except Exception as e:
            self._logger.debug(
                "Error logging edit-precision overrides: %s", e, exc_info=True
            )

        return request.model_copy(
            update={
                "temperature": new_temperature,
                "top_p": new_top_p,
                "top_k": new_top_k,
                "extra_body": extra_body,
            }
        )

    def _contains_edit_failure_prompt(self, request: ChatRequest) -> bool:
        # Prefer checking the last user message first; fall back to scanning all
        last_user_text = self._extract_last_user_text(request)
        if last_user_text and self._match_any(last_user_text):
            return True
        # Fallback: scan all text parts
        return any(self._match_any(text) for text in self._iter_all_text(request))

    def _extract_last_user_text(self, request: ChatRequest) -> str | None:
        for msg in reversed(request.messages):
            try:
                if isinstance(msg, dict):
                    role = msg.get("role")
                    content = msg.get("content")
                else:
                    role = getattr(msg, "role", None)
                    content = getattr(msg, "content", None)
            except Exception:
                continue
            if role == "user":
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    return "\n".join(self._extract_text_parts(content))
                return str(content) if content is not None else None
        return None

    def _iter_all_text(self, request: ChatRequest) -> Iterable[str]:
        for msg in request.messages:
            if isinstance(msg, dict):
                content = msg.get("content")
            else:
                content = getattr(msg, "content", None)
            if isinstance(content, str):
                yield content
            elif isinstance(content, list):
                yield from self._extract_text_parts(content)
            elif content is not None:
                yield str(content)

    @staticmethod
    def _extract_text_parts(parts: list[Any]) -> list[str]:  # type: ignore[name-defined]
        texts: list[str] = []
        for p in parts:
            if isinstance(p, dict) and p.get("type") == "text":
                t = p.get("text")
                if isinstance(t, str):
                    texts.append(t)
            elif hasattr(p, "text") and isinstance(getattr(p, "text", None), str):
                texts.append(p.text)
        return texts

    def _match_any(self, text: str) -> bool:
        if not text:
            return False
        return any(pat.search(text) for pat in self._compiled)

    def _compute_temperature(
        self, current: float | None, model_name: str | None = None
    ) -> float:
        # Get model-specific target temperature if model name is provided
        target = self._target_temperature
        if model_name and self._temperatures_config:
            target = self._temperatures_config.get_temperature_for_model(model_name)

        if current is None:
            return target

        # If already at 0.0 (deterministic), raise to target for retry flexibility
        if current <= 0.0:
            return target

        # Otherwise lower towards target for precision
        return min(current, target)

    def _compute_top_p(self, current: float | None) -> float | None:
        if self._min_top_p is None:
            return current
        if current is None:
            return self._min_top_p
        return min(current, self._min_top_p)

    def _compute_top_k(self, current: int | None) -> int | None:
        if self._target_top_k is None:
            return current
        if current is None:
            return self._target_top_k
        return min(current, self._target_top_k)
