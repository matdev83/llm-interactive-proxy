"""Deterministic auxiliary identity derivation helpers."""

from __future__ import annotations

import hashlib
from typing import Any

from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext


def _coerce_attempt_ordinal(raw_value: Any) -> int:
    if isinstance(raw_value, int):
        return max(1, raw_value)
    if isinstance(raw_value, str):
        stripped = raw_value.strip()
        if stripped:
            try:
                return max(1, int(stripped))
            except ValueError:
                return 1
    return 1


def _extract_first_user_message_text(request_data: ChatRequest | None) -> str:
    if request_data is None:
        return ""
    for message in getattr(request_data, "messages", []) or []:
        role = getattr(message, "role", None)
        if role is None and isinstance(message, dict):
            role = message.get("role")
        if role != "user":
            continue
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if content is not None:
            return str(content).strip()
    return ""


def derive_auxiliary_operation_key(
    *,
    context: RequestContext | None,
    request_data: ChatRequest | None,
    purpose: str,
) -> str:
    request_id = getattr(context, "request_id", None) if context is not None else None
    if isinstance(request_id, str) and request_id.strip():
        return f"req:{request_id.strip()}"

    first_user_message = _extract_first_user_message_text(request_data)
    if first_user_message:
        digest = hashlib.sha256(first_user_message.encode("utf-8")).hexdigest()[:16]
        return f"msg:{digest}"

    digest = hashlib.sha256((purpose or "auxiliary").encode("utf-8")).hexdigest()[:16]
    return f"aux:{digest}"


def build_auxiliary_effective_session_id(
    *,
    root_session_id: str,
    purpose: str,
    operation_key: str,
    attempt_ordinal: Any,
) -> str:
    normalized_root_session_id = root_session_id.strip()
    normalized_purpose = purpose.strip().lower() or "auxiliary"
    normalized_operation_key = operation_key.strip() or "aux:default"
    normalized_attempt_ordinal = _coerce_attempt_ordinal(attempt_ordinal)

    seed = "|".join(
        [
            normalized_root_session_id,
            normalized_purpose,
            normalized_operation_key,
            str(normalized_attempt_ordinal),
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
    return f"aux-{normalized_attempt_ordinal}-{digest}"
