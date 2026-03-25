"""Shared Quality Verifier decision flow (verifier model + XML retry + parse)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

from src.core.common.exceptions import BackendError
from src.core.common.session_key_resolver import (
    resolve_session_key_from_request_context,
)
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.notification_service_interface import INotificationService
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)
from src.core.services.quality_verifier_service import QualityVerifierService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QualityVerifierRunOutcome:
    """Result of running the verifier model for one main-model completion."""

    kind: Literal["pass", "steer", "verifier_failed"]
    steering_message: str | None = None


def _extract_text_from_openai_payload(payload: dict[str, Any]) -> str:
    pieces: list[str] = []
    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if isinstance(delta, dict):
                content_piece = delta.get("content")
                if isinstance(content_piece, str):
                    pieces.append(content_piece)
            message = choice.get("message")
            if isinstance(message, dict):
                content_piece = message.get("content")
                if isinstance(content_piece, str):
                    pieces.append(content_piece)
    top_level_content = payload.get("content")
    if isinstance(top_level_content, str):
        pieces.append(top_level_content)
    top_level_text = payload.get("text")
    if isinstance(top_level_text, str):
        pieces.append(top_level_text)
    return "".join(pieces)


def _extract_text(payload: Any) -> str:
    if payload is None:
        return ""
    value = getattr(payload, "content", payload)
    if isinstance(value, dict):
        return _extract_text_from_openai_payload(value)
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("utf-8", errors="ignore")
    return str(value)


def _response_indicates_backend_error(payload: Any) -> bool:
    status_code = getattr(payload, "status_code", None)
    if isinstance(status_code, int) and status_code >= 400:
        return True
    if isinstance(payload, ResponseEnvelope):
        if payload.status_code >= 400:
            return True
        if isinstance(payload.content, dict) and payload.content.get("error"):
            return True
    value = getattr(payload, "content", payload)
    return isinstance(value, dict) and bool(value.get("error"))


def _payload_has_non_dummy_token(payload: dict[str, Any]) -> bool:
    if payload.get("error"):
        return False
    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            for container_key in ("delta", "message"):
                container = choice.get(container_key)
                if not isinstance(container, dict):
                    continue
                for token_key in (
                    "content",
                    "tool_calls",
                    "function_call",
                    "reasoning_content",
                    "reasoning",
                    "thinking",
                    "thought",
                ):
                    token_value = container.get(token_key)
                    if token_value:
                        return True
    for token_key in ("content", "text"):
        token_value = payload.get(token_key)
        if isinstance(token_value, str) and token_value.strip():
            return True
    return False


def _chunk_contains_backend_error(chunk: Any) -> bool:
    metadata = getattr(chunk, "metadata", {}) or {}
    if isinstance(metadata, dict) and metadata.get("error"):
        return True
    chunk_content = getattr(chunk, "content", chunk)
    if isinstance(chunk_content, dict):
        if chunk_content.get("error"):
            return True
        choices = chunk_content.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if (
                    isinstance(choice, dict)
                    and choice.get("finish_reason") == "error"
                ):
                    return True
        return False
    if isinstance(chunk_content, bytes | bytearray):
        text = bytes(chunk_content).decode("utf-8", errors="ignore")
        return '"error"' in text
    if isinstance(chunk_content, str):
        return '"error"' in chunk_content
    return False


def _is_non_dummy_stream_chunk(chunk: Any) -> bool:
    metadata = getattr(chunk, "metadata", {}) or {}
    if isinstance(metadata, dict) and metadata.get("_keepalive"):
        return False
    chunk_content = getattr(chunk, "content", chunk)
    if isinstance(chunk_content, dict):
        return _payload_has_non_dummy_token(chunk_content)
    if isinstance(chunk_content, bytes | bytearray):
        text = bytes(chunk_content).decode("utf-8", errors="ignore").strip()
    elif isinstance(chunk_content, str):
        text = chunk_content.strip()
    else:
        return bool(chunk_content)
    if not text or text.startswith(":"):
        return False
    if text in {
        "[DONE]",
        '["DONE"]',
        "data: [DONE]",
        'data: ["DONE"]',
    }:
        return False
    if text.startswith("data:"):
        data_part = text[5:].strip()
        if not data_part or data_part in {"[DONE]", '["DONE"]'}:
            return False
        try:
            decoded = json.loads(data_part)
        except json.JSONDecodeError:
            return bool(data_part)
        if isinstance(decoded, dict):
            return _payload_has_non_dummy_token(decoded)
        if isinstance(decoded, str):
            return bool(decoded.strip())
        return bool(decoded)
    return True


async def _collect_stream_text_with_ttft(
    stream_response: StreamingResponseEnvelope,
    *,
    ttft_timeout_seconds: float,
) -> str | None:
    if stream_response.content is None:
        return ""
    deadline = time.monotonic() + ttft_timeout_seconds
    first_non_dummy_seen = False
    saw_error_chunk = False
    pieces: list[str] = []
    iterator = stream_response.content.__aiter__()
    try:
        while True:
            try:
                if first_non_dummy_seen:
                    stream_chunk = await anext(iterator)
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise asyncio.TimeoutError(
                            "Quality Verifier TTFT timeout exceeded"
                        )
                    stream_chunk = await asyncio.wait_for(
                        anext(iterator), timeout=remaining
                    )
            except StopAsyncIteration:
                break
            if _chunk_contains_backend_error(stream_chunk):
                saw_error_chunk = True
            if not first_non_dummy_seen and _is_non_dummy_stream_chunk(stream_chunk):
                first_non_dummy_seen = True
            piece = _extract_text(stream_chunk)
            if piece:
                pieces.append(piece)
    except asyncio.TimeoutError:
        cancel_callback = stream_response.cancel_callback
        if cancel_callback is not None:
            with contextlib.suppress(Exception):
                await cancel_callback()
        raise
    if saw_error_chunk:
        return None
    return "".join(pieces)


async def run_quality_verifier_decision(
    *,
    original_request: ChatRequest,
    assistant_text: str,
    model_spec: str,
    max_history: int | None,
    max_consecutive_failures: int,
    cooldown_seconds: int,
    ttft_timeout_seconds: float,
    backend_service: IBackendService,
    request_context: RequestContext | None,
    cancellation_coordinator: ISessionCancellationCoordinator | None,
    notification_service: INotificationService | None,
) -> QualityVerifierRunOutcome:
    """Invoke verifier model once (plus optional XML retry) and return structured outcome."""
    svc = QualityVerifierService(
        model_spec,
        max_history=max_history,
        max_consecutive_failures=max_consecutive_failures,
        cooldown_seconds=cooldown_seconds,
        notification_service=notification_service,
    )
    if not svc.is_enabled() or not svc.is_healthy():
        return QualityVerifierRunOutcome(kind="verifier_failed")

    verification_request = svc.build_verification_request(
        original_request, assistant_text
    )

    def _ensure_not_cancelled() -> None:
        if cancellation_coordinator and request_context:
            session_key = resolve_session_key_from_request_context(request_context)
            if session_key:
                cancellation_coordinator.ensure_not_cancelled(session_key)

    async def _call_verifier_once(qv_request: ChatRequest) -> str | None:
        try:
            _ensure_not_cancelled()
            ctx = request_context
            if ctx is not None:
                ctx.extensions["call_purpose"] = "quality_verifier"
            qv_response = await backend_service.chat_completions(
                qv_request,
                stream=True,
                allow_failover=True,
                context=request_context,
            )
            if _response_indicates_backend_error(qv_response):
                await svc.report_failure()
                return None
            if isinstance(qv_response, StreamingResponseEnvelope):
                qv_text = await _collect_stream_text_with_ttft(
                    qv_response,
                    ttft_timeout_seconds=ttft_timeout_seconds,
                )
                if qv_text is None:
                    await svc.report_failure()
                    return None
            else:
                qv_text = _extract_text(qv_response)
            await svc.report_success()
            return qv_text
        except asyncio.TimeoutError:
            await svc.report_failure()
            return None
        except BackendError:
            await svc.report_failure()
            return None
        except Exception:
            await svc.report_failure()
            return None

    qv_text = await _call_verifier_once(verification_request)
    qv_text = await svc.maybe_retry_verifier_for_valid_xml(
        verification_request,
        qv_text,
        _call_verifier_once,
    )
    if qv_text is None:
        return QualityVerifierRunOutcome(kind="verifier_failed")

    ok, _reason = svc.validate_quality_verifier_output_format(qv_text)
    if not ok:
        await svc.report_failure()
        return QualityVerifierRunOutcome(kind="verifier_failed")

    decision = svc.parse_quality_verifier_output(qv_text)
    steering_msg = (decision.steering_message or "").strip()
    if decision.decision == "steer" and steering_msg:
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Quality Verifier decision: steer (steering_message=%s)",
                steering_msg[:200],
                extra={
                    "session_id": getattr(request_context, "session_id", None),
                    "decision": "steer",
                    "call_purpose": "quality_verifier",
                },
            )
        return QualityVerifierRunOutcome(kind="steer", steering_message=steering_msg)

    if logger.isEnabledFor(logging.INFO):
        logger.info(
            "Quality Verifier decision: pass",
            extra={
                "session_id": getattr(request_context, "session_id", None),
                "decision": "pass",
                "call_purpose": "quality_verifier",
            },
        )
    return QualityVerifierRunOutcome(kind="pass")
