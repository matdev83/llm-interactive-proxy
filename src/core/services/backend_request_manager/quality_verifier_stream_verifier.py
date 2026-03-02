"""
Quality Verifier stream verifier service.

This service buffers and verifies streaming output when Quality Verifier is enabled,
returning corrected output when steering decisions occur.

Requirements: 4.5, 5.5
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any, cast

from src.core.common.session_key_resolver import (
    resolve_session_key_from_request_context,
)
from src.core.domain.backend_request_manager.context_models import StreamingContext
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_request_manager_components import (
    IQualityVerifierStreamVerifier,
)
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)
from src.core.services.quality_verifier_service import QualityVerifierService
from src.core.services.quality_verifier_steering_store import (
    store_pending_quality_verifier_steering,
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
    ) -> None:
        """Initialize the Quality Verifier stream verifier.

        Args:
            quality_verifier_service_factory: Factory for creating QualityVerifierService instances
            provider: Service provider for resolving IBackendService
            cancellation_coordinator: Coordinator for session cancellation checks
        """
        self._quality_verifier_service_factory = quality_verifier_service_factory
        self._provider = provider
        self._cancellation_coordinator = cancellation_coordinator
        # Keep references to background tasks to avoid premature GC and to prevent
        # "Task exception was never retrieved" warnings.
        self._background_tasks: set[asyncio.Task[Any]] = set()

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

    @staticmethod
    def _response_indicates_backend_error(payload: Any) -> bool:
        """Detect backend failure encoded as a non-exception response object."""
        status_code = getattr(payload, "status_code", None)
        if isinstance(status_code, int) and status_code >= 400:
            return True

        if isinstance(payload, ResponseEnvelope):
            if payload.status_code >= 400:
                return True
            if isinstance(payload.content, dict) and payload.content.get("error"):
                return True

        content = getattr(payload, "content", payload)
        return isinstance(content, dict) and bool(content.get("error"))

    async def _collect_streaming_quality_verifier_text(
        self,
        response: StreamingResponseEnvelope,
        *,
        ttft_timeout_seconds: float,
    ) -> str | None:
        """Collect streamed verifier output with TTFT enforcement."""
        stream = response.content
        if stream is None:
            return ""

        deadline = time.monotonic() + ttft_timeout_seconds
        first_non_dummy_seen = False
        saw_error_chunk = False
        text_parts: list[str] = []

        iterator = stream.__aiter__()

        try:
            while True:
                try:
                    if first_non_dummy_seen:
                        chunk = await anext(iterator)
                    else:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise asyncio.TimeoutError(
                                "Quality Verifier TTFT timeout exceeded"
                            )
                        chunk = await asyncio.wait_for(
                            anext(iterator), timeout=remaining
                        )
                except StopAsyncIteration:
                    break

                if self._chunk_contains_backend_error(chunk):
                    saw_error_chunk = True

                if not first_non_dummy_seen and self._is_non_dummy_stream_chunk(chunk):
                    first_non_dummy_seen = True

                text_piece = self._extract_text_from_chunk(chunk)
                if text_piece:
                    text_parts.append(text_piece)
        except asyncio.TimeoutError:
            cancel_callback = response.cancel_callback
            if cancel_callback is not None:
                with contextlib.suppress(Exception):
                    await cancel_callback()
            raise

        if saw_error_chunk:
            return None

        return "".join(text_parts)

    def _extract_text_from_response(self, payload: Any) -> str:
        """Extract text from backend response payload."""
        if payload is None:
            return ""
        value = getattr(payload, "content", payload)
        if isinstance(value, dict):
            return self._extract_text_from_openai_payload(value)
        if isinstance(value, str):
            return value
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                # Expected for non-UTF-8 content, fallback to ignore errors
                return value.decode("utf-8", errors="ignore")
            except Exception as e:
                # Unexpected exception during decoding
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Unexpected error decoding response content: %s",
                        e,
                        exc_info=True,
                    )
                return value.decode("utf-8", errors="ignore")
        return str(value)

    async def verify_or_passthrough(  # type: ignore[override, misc]
        self,
        request: ChatRequest,
        stream: AsyncIterator[ProcessedResponse],
        context: StreamingContext,
        request_context: RequestContext | None = None,
    ) -> AsyncIterator[ProcessedResponse]:
        """Pass through stream and optionally schedule assessment.

        Args:
            request: The original backend request
            stream: The streaming response chunks
            context: Streaming context with session_id, stream_id, quality_verifier_model_spec, quality_verifier_frequency, etc.

        Yields:
            ProcessedResponse chunks (verified or original)
        """
        # Check if Quality Verifier should run
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
        eligible_turn_count: int | None = context.get(
            "quality_verifier_eligible_turn_count"
        )
        skip_verification: bool = bool(
            context.get("quality_verifier_skip_verification")
        )

        should_buffer = False
        quality_verifier_service_instance: QualityVerifierService | None = None

        # Never run Quality Verifier for tool-result continuation requests.
        if QualityVerifierService.is_tool_result_followup_request(request):
            skip_verification = True

        # Never run Quality Verifier when a random replacement model is active.
        try:
            if request_context and request_context.extensions.get(
                "model_replacement_active"
            ):
                skip_verification = True
        except Exception:
            # Fail-open
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
            if eligible_turn_count is not None:
                try:
                    eligible_int = int(eligible_turn_count)
                except Exception:
                    eligible_int = 0
                should_run = eligible_int > 0 and (eligible_int % max(1, freq_int) == 0)
            else:
                should_run = QualityVerifierService.should_run_for_request(
                    request, freq_int
                )

        if should_run and logger.isEnabledFor(logging.INFO):
            session_id = str(context.get("session_id") or "")
            stream_id = str(context.get("stream_id") or "")
            logger.info(
                "Quality Verifier scheduled (session=%s stream=%s eligible_turn=%s frequency=%s model=%s)",
                session_id or "unknown",
                stream_id or "unknown",
                eligible_turn_count,
                quality_verifier_frequency,
                quality_verifier_model_spec,
            )

        if should_run:
            try:
                from src.core.interfaces.notification_service_interface import (
                    INotificationService,
                )

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

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Quality Verifier service created: instance=%s enabled=%s healthy=%s",
                        quality_verifier_service_instance is not None,
                        (
                            quality_verifier_service_instance.is_enabled()
                            if quality_verifier_service_instance
                            else False
                        ),
                        (
                            quality_verifier_service_instance.is_healthy()
                            if quality_verifier_service_instance
                            else False
                        ),
                    )

                if (
                    quality_verifier_service_instance is not None
                    and quality_verifier_service_instance.is_enabled()
                    and quality_verifier_service_instance.is_healthy()
                ):
                    should_buffer = True
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Quality Verifier buffering enabled for model %s",
                            quality_verifier_model_spec,
                        )
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
                # Expected exceptions from service creation/factory calls
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to initialize Quality Verifier service for verification: %s",
                        type(e).__name__,
                        exc_info=True,
                    )
            except Exception as e:
                # Unexpected exceptions - log with more detail for debugging
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Unexpected error initializing Quality Verifier service for verification: %s",
                        type(e).__name__,
                        exc_info=True,
                    )

        # Always forward the original stream immediately. If scheduled, we capture
        # the textual response in parallel and run the verifier asynchronously after
        # the stream completes.

        capture_enabled = bool(should_buffer)
        captured_text_parts: list[str] = []
        total_captured_bytes = 0

        async for chunk in stream:
            # Forward to client first.
            yield chunk

            if not capture_enabled:
                continue

            text_piece = self._extract_text_from_chunk(chunk)
            if not text_piece:
                continue

            captured_text_parts.append(text_piece)
            total_captured_bytes += len(text_piece.encode("utf-8", errors="ignore"))
            if total_captured_bytes > MAX_QUALITY_VERIFIER_BUFFER_BYTES:
                capture_enabled = False
                captured_text_parts.clear()
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Quality Verifier capture limit exceeded (%d bytes); skipping assessment for this turn",
                        total_captured_bytes,
                    )

        combined_text = "".join(captured_text_parts).strip()
        if not combined_text:
            return

        if not should_buffer:
            return

        async def _run_assessment_in_background() -> None:
            try:
                backend_service: IBackendService = self._provider.get_required_service(
                    cast(type, IBackendService)
                )

                from src.core.interfaces.notification_service_interface import (
                    INotificationService,
                )

                notification_service = self._provider.get_service(
                    cast(Any, INotificationService)
                )

                svc: QualityVerifierService = (
                    self._quality_verifier_service_factory.create(
                        quality_verifier_model_spec or "",
                        max_history=quality_verifier_max_history,
                        max_consecutive_failures=quality_verifier_max_consecutive_failures,
                        cooldown_seconds=quality_verifier_cooldown_seconds,
                        notification_service=notification_service,
                    )
                )

                if not svc.is_enabled() or not svc.is_healthy():
                    return

                # Cancellation gate (best effort)
                if self._cancellation_coordinator and request_context:
                    cancel_session_key = resolve_session_key_from_request_context(
                        request_context
                    )
                    if cancel_session_key:
                        self._cancellation_coordinator.ensure_not_cancelled(
                            cancel_session_key
                        )

                verification_request = svc.build_verification_request(
                    request, combined_text
                )

                try:
                    verifier_response = await backend_service.chat_completions(
                        verification_request,
                        stream=True,
                        allow_failover=True,
                        context=request_context,
                    )
                except Exception:
                    await svc.report_failure()
                    return

                if self._response_indicates_backend_error(verifier_response):
                    await svc.report_failure()
                    return

                try:
                    if isinstance(verifier_response, StreamingResponseEnvelope):
                        verifier_text = await self._collect_streaming_quality_verifier_text(
                            verifier_response,
                            ttft_timeout_seconds=quality_verifier_ttft_timeout_seconds,
                        )
                        if verifier_text is None:
                            await svc.report_failure()
                            return
                    else:
                        verifier_text = self._extract_text_from_response(
                            verifier_response
                        )
                except asyncio.TimeoutError:
                    await svc.report_failure()
                    return
                except Exception:
                    await svc.report_failure()
                    return

                is_valid, _reason = svc.validate_quality_verifier_output_format(
                    verifier_text or ""
                )
                if not is_valid:
                    # Soft fail: ignore bad formats. Count as failure so circuit breaker can
                    # disable a misconfigured verifier without impacting the client.
                    await svc.report_failure()
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Quality Verifier output invalid; ignoring (%s)",
                            _reason or "invalid format",
                        )
                    return

                decision = svc.parse_quality_verifier_output(verifier_text or "")
                steering_msg = (decision.steering_message or "").strip()
                if decision.decision != "steer" or not steering_msg:
                    await svc.report_success()
                    return

                await svc.report_success()

                if request_context is None:
                    return
                app_state = getattr(request_context, "app_state", None)
                if app_state is None:
                    return

                session_key_value = (
                    request_context.extensions.get(
                        "quality_verifier_effective_session_id"
                    )
                    if hasattr(request_context, "extensions")
                    else None
                )
                session_key = str(
                    session_key_value
                    or context.get("session_id")
                    or request_context.session_id
                    or ""
                ).strip()
                if not session_key:
                    return

                store_pending_quality_verifier_steering(
                    app_state=app_state,
                    session_key=session_key,
                    steering_message=steering_msg,
                )
            except Exception:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Quality Verifier background assessment failed",
                        exc_info=True,
                    )

        try:
            task = asyncio.create_task(_run_assessment_in_background())
            self._background_tasks.add(task)

            def _consume_task_result(t: asyncio.Task[Any]) -> None:
                self._background_tasks.discard(t)
                with contextlib.suppress(Exception):
                    _ = t.result()

            task.add_done_callback(_consume_task_result)
        except Exception:
            # If we cannot schedule, just skip assessment.
            return
