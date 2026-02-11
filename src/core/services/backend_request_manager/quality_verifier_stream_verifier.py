"""
Quality Verifier stream verifier service.

This service buffers and verifies streaming output when Quality Verifier is enabled,
returning corrected output when steering decisions occur.

Requirements: 4.5, 5.5
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from typing import Any, cast

from src.core.domain.backend_request_manager.context_models import StreamingContext
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
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
from src.core.transport.session_key_resolver import (
    resolve_session_key_from_request_context,
)

logger = logging.getLogger(__name__)

# Maximum buffer size for Quality Verifier (1MB)
# Responses exceeding this limit will fail-open to avoid OOM
MAX_QUALITY_VERIFIER_BUFFER_BYTES = 1024 * 1024


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
        content = chunk.content
        if isinstance(content, str):
            return content
        if isinstance(content, bytes):
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError:
                # Expected for non-UTF-8 content, fallback to ignore errors
                return content.decode("utf-8", errors="ignore")
            except Exception as e:
                # Unexpected exception during decoding
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Unexpected error decoding chunk content: %s", e, exc_info=True
                    )
                return content.decode("utf-8", errors="ignore")
        return str(content) if content is not None else ""

    def _extract_text_from_response(self, payload: Any) -> str:
        """Extract text from backend response payload."""
        if payload is None:
            return ""
        value = getattr(payload, "content", payload)
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
        quality_verifier_model_spec: str | None = context.get("quality_verifier_model_spec")
        quality_verifier_frequency: int = context.get("quality_verifier_frequency", 10)
        quality_verifier_max_history: int | None = context.get("quality_verifier_max_history")
        quality_verifier_max_consecutive_failures: int = context.get(
            "quality_verifier_max_consecutive_failures", 5
        )
        quality_verifier_cooldown_seconds: int = context.get("quality_verifier_cooldown_seconds", 300)
        eligible_turn_count: int | None = context.get("quality_verifier_eligible_turn_count")
        skip_verification: bool = bool(context.get("quality_verifier_skip_verification"))

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
                freq_int = int(quality_verifier_frequency) if int(quality_verifier_frequency) > 0 else 1
            except Exception:
                freq_int = 10
            if eligible_turn_count is not None:
                try:
                    eligible_int = int(eligible_turn_count)
                except Exception:
                    eligible_int = 0
                should_run = eligible_int > 0 and (eligible_int % max(1, freq_int) == 0)
            else:
                should_run = QualityVerifierService.should_run_for_request(request, freq_int)

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

            verification_request = quality_verifier_service_instance.build_verification_request(
                request, combined_text
            )

            def _ensure_quality_verifier_not_cancelled() -> None:
                if self._cancellation_coordinator and request_context:
                    session_key = resolve_session_key_from_request_context(
                        request_context
                    )
                    if session_key:
                        self._cancellation_coordinator.ensure_not_cancelled(session_key)

            async def _call_quality_verifier_once(quality_verifier_request: ChatRequest) -> str | None:
                try:
                    _ensure_quality_verifier_not_cancelled()
                    quality_verifier_response = await backend_service.chat_completions(
                        quality_verifier_request,
                        stream=False,
                        allow_failover=True,
                        context=request_context,
                    )
                    await quality_verifier_service_instance.report_success()
                    return self._extract_text_from_response(quality_verifier_response)
                except Exception as e:
                    await quality_verifier_service_instance.report_failure()
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Quality Verifier model call failed (%s); failing-open and forwarding original chunks",
                            type(e).__name__,
                            exc_info=True,
                        )
                    return None

            quality_verifier_text = await _call_quality_verifier_once(verification_request)
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
                retry_request = (
                    quality_verifier_service_instance.build_invalid_format_retry_request(
                        verification_request,
                        quality_verifier_text,
                        invalid_reason,
                    )
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

            # If no steering needed, pass through original chunks
            if decision.decision != "steer" or not steering_msg:
                for buffered in buffered_chunks:
                    yield buffered
                return

            # Build correction request and get corrected response
            correction_request = quality_verifier_service_instance.build_correction_request(
                request, combined_text, steering_msg
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
