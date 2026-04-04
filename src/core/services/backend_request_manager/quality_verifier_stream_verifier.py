"""
Quality Verifier stream verifier service.

On scheduled verifier turns, buffers the main-model stream until the verifier
(and optional steering recall) completes, then yields either the original
buffer, the recall stream, or a fail-open passthrough.

Requirements: 4.5, 5.5
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, cast

from src.core.domain.backend_request_manager.context_models import StreamingContext
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.backend_request_manager_components import (
    IQualityVerifierStreamVerifier,
)
from src.core.interfaces.backend_request_manager_interface import IBackendRequestManager
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.backend_work_guard_interface import IBackendWorkGuard
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.notification_service_interface import INotificationService
from src.core.interfaces.quality_verifier_turn_ledger_interface import (
    IQualityVerifierTurnLedger,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)
from src.core.services.quality_verifier_orchestrator import (
    run_quality_verifier_decision,
)
from src.core.services.quality_verifier_recall_context import (
    fork_request_context_for_quality_verifier_steering_recall,
)
from src.core.services.quality_verifier_service import QualityVerifierService
from src.core.services.quality_verifier_steering_messages import (
    append_quality_verifier_steering_system_message,
)

logger = logging.getLogger(__name__)

# Maximum buffer size for Quality Verifier (1MB)
# Responses exceeding this limit will fail-open to avoid OOM
MAX_QUALITY_VERIFIER_BUFFER_BYTES = 1024 * 1024
DEFAULT_QUALITY_VERIFIER_TTFT_TIMEOUT_SECONDS = 30.0


class QualityVerifierStreamVerifier(IQualityVerifierStreamVerifier):
    """Service for buffering and verifying streaming output when Quality Verifier is enabled."""

    def __init__(
        self,
        quality_verifier_service_factory: Any,  # IQualityVerifierServiceFactory
        provider: IServiceProvider,
        cancellation_coordinator: ISessionCancellationCoordinator | None = None,
        turn_ledger: IQualityVerifierTurnLedger | None = None,
    ) -> None:
        """Initialize the Quality Verifier stream verifier.

        Args:
            quality_verifier_service_factory: Factory for creating QualityVerifierService instances
            provider: Service provider for resolving backend services
            cancellation_coordinator: Coordinator for session cancellation checks
            turn_ledger: Resets eligible-turn counter after a verification episode
        """
        self._quality_verifier_service_factory = quality_verifier_service_factory
        self._provider = provider
        self._cancellation_coordinator = cancellation_coordinator
        self._turn_ledger = turn_ledger

    def _extract_text_from_chunk(self, chunk: ProcessedResponse) -> str:
        """Extract textual content from a streaming chunk."""
        content = getattr(chunk, "content", chunk)
        if isinstance(content, dict):
            return self._extract_text_from_openai_payload(content)
        if isinstance(content, str):
            return self._extract_text_from_sse_payload(content)
        if isinstance(content, bytes):
            try:
                decoded = content.decode("utf-8")
            except UnicodeDecodeError:
                # Expected for non-UTF-8 content, fallback to ignore errors
                decoded = content.decode("utf-8", errors="ignore")
            except Exception as e:
                # Unexpected exception during decoding
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Unexpected error decoding chunk content: %s", e, exc_info=True
                    )
                decoded = content.decode("utf-8", errors="ignore")
            return self._extract_text_from_sse_payload(decoded)
        return str(content) if content is not None else ""

    @staticmethod
    def _extract_text_from_openai_payload(payload: dict[str, Any]) -> str:
        """Extract assistant text from an OpenAI-style payload dict."""
        parts: list[str] = []

        choices = payload.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue

                delta = choice.get("delta")
                if isinstance(delta, dict):
                    delta_content = delta.get("content")
                    if isinstance(delta_content, str):
                        parts.append(delta_content)

                message = choice.get("message")
                if isinstance(message, dict):
                    message_content = message.get("content")
                    if isinstance(message_content, str):
                        parts.append(message_content)

        top_level_content = payload.get("content")
        if isinstance(top_level_content, str):
            parts.append(top_level_content)

        top_level_text = payload.get("text")
        if isinstance(top_level_text, str):
            parts.append(top_level_text)

        return "".join(parts)

    def _extract_text_from_sse_payload(self, payload: str) -> str:
        """Extract textual content from SSE-like payload strings."""
        stripped = payload.strip()
        if not stripped:
            return ""

        if not any(line.lstrip().startswith("data:") for line in stripped.splitlines()):
            # Non-SSE raw payload
            return payload

        parts: list[str] = []
        for raw_line in stripped.splitlines():
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue

            data_part = line[5:].strip()
            if not data_part or data_part in {"[DONE]", '["DONE"]'}:
                continue

            try:
                decoded = json.loads(data_part)
            except json.JSONDecodeError:
                parts.append(data_part)
                continue

            if isinstance(decoded, dict):
                piece = self._extract_text_from_openai_payload(decoded)
                if piece:
                    parts.append(piece)
            elif isinstance(decoded, str):
                parts.append(decoded)

        return "".join(parts)

    @staticmethod
    def _coerce_ttft_timeout_seconds(raw_value: Any) -> float:
        """Normalize TTFT timeout to a safe positive float in seconds."""
        try:
            timeout_value = float(raw_value)
        except (TypeError, ValueError):
            timeout_value = DEFAULT_QUALITY_VERIFIER_TTFT_TIMEOUT_SECONDS

        if timeout_value <= 0:
            return DEFAULT_QUALITY_VERIFIER_TTFT_TIMEOUT_SECONDS

        return timeout_value

    def _chunk_contains_backend_error(self, chunk: Any) -> bool:
        """Return True when a streamed chunk carries an upstream error marker."""
        metadata = getattr(chunk, "metadata", {}) or {}
        if isinstance(metadata, dict) and metadata.get("error"):
            return True

        content = getattr(chunk, "content", chunk)
        if isinstance(content, dict):
            if content.get("error"):
                return True

            choices = content.get("choices")
            if isinstance(choices, list):
                for choice in choices:
                    if (
                        isinstance(choice, dict)
                        and choice.get("finish_reason") == "error"
                    ):
                        return True
            return False

        if isinstance(content, bytes | bytearray):
            text = bytes(content).decode("utf-8", errors="ignore")
            return '"error"' in text

        if isinstance(content, str):
            return '"error"' in content

        return False

    @staticmethod
    def _payload_has_non_dummy_token(payload: dict[str, Any]) -> bool:
        """Return True when payload contains non-keepalive model output."""
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

    def _is_non_dummy_stream_chunk(self, chunk: Any) -> bool:
        """Detect the first real token while ignoring keepalives and done markers."""
        metadata = getattr(chunk, "metadata", {}) or {}
        if isinstance(metadata, dict) and metadata.get("_keepalive"):
            return False

        content = getattr(chunk, "content", chunk)
        if isinstance(content, dict):
            return self._payload_has_non_dummy_token(content)

        if isinstance(content, bytes | bytearray):
            text = bytes(content).decode("utf-8", errors="ignore").strip()
        elif isinstance(content, str):
            text = content.strip()
        else:
            return bool(content)

        if not text or text.startswith(":"):
            return False

        if text in {"[DONE]", '["DONE"]', "data: [DONE]", 'data: ["DONE"]'}:
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
                return self._payload_has_non_dummy_token(decoded)
            if isinstance(decoded, str):
                return bool(decoded.strip())
            return bool(decoded)

        return True

    def _quality_verifier_session_key(
        self, request_context: RequestContext | None
    ) -> str:
        if request_context is not None:
            try:
                raw = request_context.extensions.get(
                    "quality_verifier_effective_session_id"
                )
                if raw is not None and str(raw).strip():
                    return str(raw).strip()
            except Exception:
                pass
            sid = getattr(request_context, "session_id", None)
            if isinstance(sid, str) and sid.strip():
                return sid.strip()
        return ""

    def _maybe_reset_turn_ledger(
        self,
        *,
        should_buffer: bool,
        buffer_overflow: bool,
        request_context: RequestContext | None,
        context: StreamingContext,
    ) -> None:
        """Clear eligible-turn state when ``turn_ledger`` is set or resolvable from the provider."""
        if not should_buffer or buffer_overflow:
            return

        ledger = self._turn_ledger
        if ledger is None:
            try:
                ledger = self._provider.get_required_service(
                    cast(type, IQualityVerifierTurnLedger)  # type: ignore[type-abstract]
                )
            except Exception:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Quality Verifier stream: turn ledger unavailable",
                        exc_info=True,
                    )
                return

        key = self._quality_verifier_session_key(request_context)
        if not key:
            key = str(context.get("session_id") or "").strip()
        if not key:
            return
        session_obj = (
            getattr(request_context, "state", None) if request_context else None
        )
        try:
            ledger.reset_quality_verifier_eligible_turn_count(key, session_obj)
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Quality Verifier turn ledger reset failed", exc_info=True)

    async def verify_or_passthrough(  # type: ignore[override, misc]
        self,
        request: ChatRequest,
        stream: AsyncIterator[ProcessedResponse],
        context: StreamingContext,
        request_context: RequestContext | None = None,
    ) -> AsyncIterator[ProcessedResponse]:
        """Buffer on scheduled verifier turns; run verifier; optional steering recall.

        Yields:
            ``ProcessedResponse`` chunks (original buffer, recall stream, or passthrough).
        """
        quality_verifier_model_spec: str | None = context.get(
            "quality_verifier_model_spec"
        )
        quality_verifier_frequency: int = context.get("quality_verifier_frequency", 10)
        quality_verifier_max_history: int | None = context.get(
            "quality_verifier_max_history"
        )
        quality_verifier_max_consecutive_failures: int = context.get(
            "quality_verifier_max_consecutive_failures", 5
        )
        quality_verifier_cooldown_seconds: int = context.get(
            "quality_verifier_cooldown_seconds", 300
        )
        quality_verifier_ttft_timeout_seconds: float = (
            self._coerce_ttft_timeout_seconds(
                context.get(
                    "quality_verifier_ttft_timeout_seconds",
                    DEFAULT_QUALITY_VERIFIER_TTFT_TIMEOUT_SECONDS,
                )
            )
        )
        eligible_turn_raw: Any = context.get("quality_verifier_eligible_turn_raw")
        if eligible_turn_raw is None:
            eligible_turn_raw = context.get("quality_verifier_eligible_turn_count")
        skip_verification: bool = bool(
            context.get("quality_verifier_skip_verification")
        )

        should_buffer = False
        quality_verifier_service_instance: QualityVerifierService | None = None

        if QualityVerifierService.is_tool_result_followup_request(request):
            skip_verification = True

        try:
            if request_context and request_context.extensions.get(
                "model_replacement_active"
            ):
                skip_verification = True
        except Exception:
            pass

        should_run = False
        if not skip_verification and quality_verifier_model_spec:
            try:
                freq_int = (
                    int(quality_verifier_frequency)
                    if int(quality_verifier_frequency) > 0
                    else 1
                )
            except Exception:
                freq_int = 10
            should_run = QualityVerifierService.should_run_verification(
                request,
                freq_int,
                eligible_turn_raw=eligible_turn_raw,
            )

        if should_run and logger.isEnabledFor(logging.INFO):
            session_id = str(context.get("session_id") or "")
            stream_id = str(context.get("stream_id") or "")
            logger.info(
                "Quality Verifier scheduled (session=%s stream=%s eligible_turn=%s frequency=%s model=%s)",
                session_id or "unknown",
                stream_id or "unknown",
                QualityVerifierService.coerce_eligible_turn_floor(eligible_turn_raw),
                quality_verifier_frequency,
                quality_verifier_model_spec,
            )

        if should_run:
            try:
                notification_service = self._provider.get_service(
                    cast(Any, INotificationService)
                )

                quality_verifier_service_instance = self._quality_verifier_service_factory.create(
                    quality_verifier_model_spec,
                    max_history=quality_verifier_max_history,
                    max_consecutive_failures=quality_verifier_max_consecutive_failures,
                    cooldown_seconds=quality_verifier_cooldown_seconds,
                    notification_service=notification_service,
                )

                if (
                    quality_verifier_service_instance is not None
                    and quality_verifier_service_instance.is_enabled()
                    and quality_verifier_service_instance.is_healthy()
                ):
                    should_buffer = True
                elif (
                    quality_verifier_service_instance
                    and not quality_verifier_service_instance.is_healthy()
                    and logger.isEnabledFor(logging.DEBUG)
                ):
                    logger.debug(
                        "Quality Verifier skipped due to circuit breaker for model %s",
                        quality_verifier_model_spec,
                    )

            except (RuntimeError, AttributeError, TypeError, ValueError) as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to initialize Quality Verifier service for verification: %s",
                        type(e).__name__,
                        exc_info=True,
                    )
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Unexpected error initializing Quality Verifier service for verification: %s",
                        type(e).__name__,
                        exc_info=True,
                    )

        if not should_buffer:
            async for chunk in stream:
                yield chunk
            return

        buffered: list[ProcessedResponse] = []
        text_parts: list[str] = []
        total_captured_bytes = 0
        buffer_overflow = False

        async for chunk in stream:
            text_piece = self._extract_text_from_chunk(chunk)
            piece_bytes = len(text_piece.encode("utf-8", errors="ignore"))
            if not buffer_overflow:
                if (
                    total_captured_bytes + piece_bytes
                    > MAX_QUALITY_VERIFIER_BUFFER_BYTES
                ):
                    buffer_overflow = True
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Quality Verifier buffer exceeded %d bytes; passthrough without verification",
                            MAX_QUALITY_VERIFIER_BUFFER_BYTES,
                        )
                    for prior in buffered:
                        yield prior
                    yield chunk
                    buffered.clear()
                    text_parts.clear()
                    continue
                buffered.append(chunk)
                if text_piece:
                    text_parts.append(text_piece)
                total_captured_bytes += piece_bytes
            else:
                yield chunk

        if buffer_overflow:
            return

        combined_text = "".join(text_parts).strip()
        if not buffered:
            return

        # No extractable text: verifier is not run; do not reset the eligible-turn ledger.
        if not combined_text:
            for prior in buffered:
                yield prior
            return

        backend_service: IBackendService = self._provider.get_required_service(
            cast(type, IBackendService)
        )
        notification_service = self._provider.get_service(
            cast(Any, INotificationService)
        )
        backend_work_guard = self._provider.get_service(cast(type, IBackendWorkGuard))

        outcome = await run_quality_verifier_decision(
            original_request=request,
            assistant_text=combined_text,
            model_spec=str(quality_verifier_model_spec or ""),
            max_history=quality_verifier_max_history,
            max_consecutive_failures=quality_verifier_max_consecutive_failures,
            cooldown_seconds=quality_verifier_cooldown_seconds,
            ttft_timeout_seconds=quality_verifier_ttft_timeout_seconds,
            backend_service=backend_service,
            request_context=request_context,
            cancellation_coordinator=self._cancellation_coordinator,
            notification_service=notification_service,
            backend_work_guard=backend_work_guard,
        )

        self._maybe_reset_turn_ledger(
            should_buffer=True,
            buffer_overflow=False,
            request_context=request_context,
            context=context,
        )

        if outcome.kind != "steer" or not (outcome.steering_message or "").strip():
            for prior in buffered:
                yield prior
            return

        steering_msg = (outcome.steering_message or "").strip()
        if request_context is None:
            # Ledger already reset above; replay buffer (inline recall needs RequestContext).
            for prior in buffered:
                yield prior
            return

        steered = append_quality_verifier_steering_system_message(request, steering_msg)
        steered = steered.model_copy(update={"stream": True})
        recall_ctx = fork_request_context_for_quality_verifier_steering_recall(
            request_context
        )
        session_id = str(context.get("session_id") or "").strip()
        if not session_id and request_context and request_context.session_id:
            session_id = str(request_context.session_id).strip()

        try:
            brm: IBackendRequestManager = self._provider.get_required_service(
                cast(type, IBackendRequestManager)
            )
            recall_env = await brm.process_backend_request(
                steered, session_id, recall_ctx
            )
        except Exception:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Quality Verifier steering recall failed; returning original stream",
                    exc_info=True,
                )
            for prior in buffered:
                yield prior
            return

        if (
            isinstance(recall_env, StreamingResponseEnvelope)
            and recall_env.content is not None
        ):
            try:
                async for recall_chunk in recall_env.content:
                    yield recall_chunk
                return
            except Exception:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Quality Verifier steering recall stream failed; returning original",
                        exc_info=True,
                    )

        for prior in buffered:
            yield prior
