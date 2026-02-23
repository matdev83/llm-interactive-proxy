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
import re
import time
from collections.abc import AsyncIterator
from typing import Any, cast

from src.core.common.exceptions import BackendError
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

    async def verify_or_passthrough(  # type: ignore[override, misc]  # noqa: C901
        self,
        request: ChatRequest,
        stream: AsyncIterator[ProcessedResponse],
        context: StreamingContext,
        request_context: RequestContext | None = None,
    ) -> AsyncIterator[ProcessedResponse]:
        """Return verified stream or original stream when no steering is needed.

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

        # If Quality Verifier is not enabled, pass through original stream
        if not should_buffer:
            async for chunk in stream:
                yield chunk
            return

        # Buffer chunks for verification
        buffered_chunks: list[ProcessedResponse] = []
        text_fragments: list[str] = []
        total_buffered_bytes = 0

        async for chunk in stream:
            buffered_chunks.append(chunk)
            text_piece = self._extract_text_from_chunk(chunk)
            if text_piece:
                text_fragments.append(text_piece)
                total_buffered_bytes += len(text_piece.encode("utf-8", errors="ignore"))

            # Check for buffer limit to avoid OOM (Fail-open)
            if total_buffered_bytes > MAX_QUALITY_VERIFIER_BUFFER_BYTES:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Quality Verifier buffer limit exceeded (%d bytes); failing-open and forwarding original chunks",
                        total_buffered_bytes,
                    )
                # Yield what we have so far
                for buffered in buffered_chunks:
                    yield buffered
                # Yield the rest of the stream
                async for remaining_chunk in stream:
                    yield remaining_chunk
                return

        if not buffered_chunks:
            return

        combined_text = "".join(text_fragments)
        if not combined_text.strip():
            # Empty text, just yield buffered chunks
            for buffered in buffered_chunks:
                yield buffered
            return

        # Perform verification
        try:
            backend_service: IBackendService = self._provider.get_required_service(
                cast(type, IBackendService)
            )

            if not quality_verifier_service_instance:
                # Should not happen given the check above, but safe fallback
                from src.core.interfaces.notification_service_interface import (
                    INotificationService,
                )

                notification_service = self._provider.get_service(
                    cast(Any, INotificationService)
                )

                created_instance = self._quality_verifier_service_factory.create(
                    quality_verifier_model_spec or "",
                    max_history=quality_verifier_max_history,
                    max_consecutive_failures=quality_verifier_max_consecutive_failures,
                    cooldown_seconds=quality_verifier_cooldown_seconds,
                    notification_service=notification_service,
                )

                if created_instance is None:
                    # Fail-open: return original chunks if service creation fails
                    for buffered in buffered_chunks:
                        yield buffered
                    return
                quality_verifier_service_instance = created_instance

            # Type guard: ensure quality_verifier_service_instance is not None
            if quality_verifier_service_instance is None:
                for buffered in buffered_chunks:
                    yield buffered
                return

            verification_request = (
                quality_verifier_service_instance.build_verification_request(
                    request, combined_text
                )
            )

            def _ensure_quality_verifier_not_cancelled() -> None:
                if self._cancellation_coordinator and request_context:
                    session_key = resolve_session_key_from_request_context(
                        request_context
                    )
                    if session_key:
                        self._cancellation_coordinator.ensure_not_cancelled(session_key)

            async def _call_quality_verifier_once(
                quality_verifier_request: ChatRequest,
            ) -> str | None:
                try:
                    _ensure_quality_verifier_not_cancelled()

                    if logger.isEnabledFor(logging.INFO):
                        session_id = str(context.get("session_id") or "")
                        stream_id = str(context.get("stream_id") or "")
                        logger.info(
                            "Quality Verifier calling backend (session=%s stream=%s model=%s)",
                            session_id or "unknown",
                            stream_id or "unknown",
                            quality_verifier_model_spec,
                        )

                    quality_verifier_response = await backend_service.chat_completions(
                        quality_verifier_request,
                        stream=True,
                        allow_failover=True,
                        context=request_context,
                    )

                    if self._response_indicates_backend_error(
                        quality_verifier_response
                    ):
                        await quality_verifier_service_instance.report_failure()
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Quality Verifier model returned error response; "
                                "failing-open and forwarding original chunks"
                            )
                        return None

                    if isinstance(quality_verifier_response, StreamingResponseEnvelope):
                        quality_verifier_text = await self._collect_streaming_quality_verifier_text(
                            quality_verifier_response,
                            ttft_timeout_seconds=quality_verifier_ttft_timeout_seconds,
                        )
                        if quality_verifier_text is None:
                            await quality_verifier_service_instance.report_failure()
                            if logger.isEnabledFor(logging.WARNING):
                                logger.warning(
                                    "Quality Verifier stream ended with backend error; "
                                    "failing-open and forwarding original chunks"
                                )
                            return None
                    else:
                        quality_verifier_text = self._extract_text_from_response(
                            quality_verifier_response
                        )

                    await quality_verifier_service_instance.report_success()
                    return quality_verifier_text
                except asyncio.TimeoutError:
                    await quality_verifier_service_instance.report_failure()
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Quality Verifier TTFT timeout after %.1fs; "
                            "failing-open and forwarding original chunks",
                            quality_verifier_ttft_timeout_seconds,
                        )
                    return None
                except BackendError as e:
                    await quality_verifier_service_instance.report_failure()
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Quality Verifier model call failed (%s); "
                            "failing-open and forwarding original chunks",
                            e.message,
                        )
                    return None
                except Exception as e:
                    await quality_verifier_service_instance.report_failure()
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Quality Verifier model call failed (%s); failing-open and forwarding original chunks",
                            type(e).__name__,
                            exc_info=True,
                        )
                    return None

            quality_verifier_text = await _call_quality_verifier_once(
                verification_request
            )
            if quality_verifier_text is None:
                for buffered in buffered_chunks:
                    yield buffered
                return

            is_valid_format, invalid_reason = (
                quality_verifier_service_instance.validate_quality_verifier_output_format(
                    quality_verifier_text
                )
            )
            if not is_valid_format:
                _session_id = str(context.get("session_id") or "unknown")
                if logger.isEnabledFor(logging.DEBUG):
                    snippet = (
                        quality_verifier_text[:500]
                        if quality_verifier_text
                        else "(empty)"
                    )
                    logger.debug(
                        "Quality Verifier response format invalid (session=%s reason=%s): %s",
                        _session_id,
                        invalid_reason or "unknown",
                        snippet,
                    )
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Quality Verifier retrying due to invalid format (session=%s reason=%s)",
                        _session_id,
                        invalid_reason or "unknown",
                    )
                retry_request = quality_verifier_service_instance.build_invalid_format_retry_request(
                    verification_request,
                    quality_verifier_text,
                    invalid_reason,
                )
                retry_text = await _call_quality_verifier_once(retry_request)
                if retry_text is None:
                    for buffered in buffered_chunks:
                        yield buffered
                    return
                quality_verifier_text = retry_text

                is_valid_format, invalid_reason = (
                    quality_verifier_service_instance.validate_quality_verifier_output_format(
                        quality_verifier_text
                    )
                )
                if not is_valid_format:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Quality Verifier response still invalid after single retry; failing-open and forwarding original chunks (%s)",
                            invalid_reason or "invalid format",
                        )
                    for buffered in buffered_chunks:
                        yield buffered
                    return

            decision = quality_verifier_service_instance.parse_quality_verifier_output(
                quality_verifier_text
            )
            steering_msg = (decision.steering_message or "").strip()

            _session_id = str(context.get("session_id") or "unknown")
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Quality Verifier decision: %s (session=%s has_steering_message=%s)",
                    decision.decision,
                    _session_id,
                    bool(steering_msg),
                )

            # If no steering needed, pass through original chunks
            if decision.decision != "steer" or not steering_msg:
                for buffered in buffered_chunks:
                    yield buffered
                return

            # Build correction request and get corrected response
            correction_request = (
                quality_verifier_service_instance.build_correction_request(
                    request, combined_text, steering_msg
                )
            )

            # Tag the quality verifier steering message as non-forwardable and set injection boundary
            if correction_request.messages and request_context:
                from src.core.domain.non_forwardable import NonForwardableTagScope
                from src.core.interfaces.non_forwardable_interface import (
                    INonForwardableMessageIdentityService,
                    INonForwardableMessageRegistry,
                )
                from src.core.services.non_forwardable_message_enforcer import (
                    PROXY_INJECTED_MESSAGES_START_INDEX_KEY,
                )

                # Get registry and identity service from provider
                non_forwardable_registry = self._provider.get_service(
                    cast(type, INonForwardableMessageRegistry)
                )
                non_forwardable_identity_service = self._provider.get_service(
                    cast(type, INonForwardableMessageIdentityService)
                )

                # Find the steering message (last user message with steering marker)
                steering_message = None
                for msg in reversed(correction_request.messages):
                    if msg.role == "user" and "QUALITY VERIFIER STEERING" in (
                        str(msg.content) or ""
                    ):
                        steering_message = msg
                        break

                if (
                    steering_message
                    and non_forwardable_registry
                    and non_forwardable_identity_service
                ):
                    session_id = request_context.session_id or "unknown"
                    try:
                        identity = non_forwardable_identity_service.compute_identity(
                            steering_message
                        )
                        await non_forwardable_registry.tag_identities(
                            session_id=session_id,
                            identities=[identity],
                            scope=NonForwardableTagScope.CLIENT_HISTORY_ONLY,
                            reason="quality_verifier_steering",
                        )
                        # Set injection boundary
                        injection_start_index = len(request.messages)
                        request_context.extensions[
                            PROXY_INJECTED_MESSAGES_START_INDEX_KEY
                        ] = injection_start_index
                    except Exception as e:
                        # LOG BUT DO NOT BREAK MAIN FLOW
                        # Steering is not a security feature, tagging failure is acceptable here
                        # if it means we can still recover the session
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Failed to tag quality verifier steering message as non-forwardable: %s",
                                e,
                                exc_info=True,
                            )

            # Cancellation gate: ensure session is not cancelled before Quality Verifier correction backend call
            if self._cancellation_coordinator and request_context:
                session_key = resolve_session_key_from_request_context(request_context)
                if session_key:
                    self._cancellation_coordinator.ensure_not_cancelled(session_key)

            try:
                if logger.isEnabledFor(logging.INFO):
                    session_id = str(context.get("session_id") or "")
                    stream_id = str(context.get("stream_id") or "")
                    logger.info(
                        "Quality Verifier requesting correction (session=%s stream=%s)",
                        session_id or "unknown",
                        stream_id or "unknown",
                    )
                corrected_response = await backend_service.chat_completions(
                    correction_request,
                    stream=False,
                    allow_failover=True,
                    context=request_context,
                )
                corrected_text = self._extract_text_from_response(corrected_response)
            except Exception as e:
                # Fail-open if correction call fails
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Quality Verifier correction call failed (%s); failing-open and forwarding original chunks",
                        type(e).__name__,
                        exc_info=True,
                    )
                for buffered in buffered_chunks:
                    yield buffered
                return

            # Prevent internal override markers from reaching the client.
            cleaned = re.sub(
                r"<override_quality_verifier>[\s\S]*?</override_quality_verifier>",
                "",
                str(corrected_text or ""),
                flags=re.IGNORECASE,
            )
            cleaned = re.sub(
                r"<override_quality_verifier\s*/\s*>",
                "",
                cleaned,
                flags=re.IGNORECASE,
            ).strip()

            if not cleaned:
                # Fail-open: forward original chunks if the correction contains no usable content.
                for buffered in buffered_chunks:
                    yield buffered
                return

            if logger.isEnabledFor(logging.INFO):
                _session_id = str(context.get("session_id") or "unknown")
                logger.info(
                    "Quality Verifier steering applied (session=%s corrected_length=%d)",
                    _session_id,
                    len(cleaned),
                )

            # Yield corrected output with steering replacement marker
            yield ProcessedResponse(
                content=cleaned,
                metadata={
                    "corrected_by_quality_verifier": True,
                    "is_done": True,
                    "quality_verifier_decision": "steer",
                    "_steering_replacement": True,
                },
            )

        except Exception as e:
            # Final catch-all for any unexpected errors during verification/correction
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Quality Verifier process encountered an unexpected error (%s); "
                    "failing-open and forwarding original chunks",
                    type(e).__name__,
                    exc_info=True,
                )
            for buffered in buffered_chunks:
                yield buffered
