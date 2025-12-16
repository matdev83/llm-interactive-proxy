"""Response handling logic for backend completion flow."""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any

from fastapi import HTTPException

from src.connectors.base import LLMBackend
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    LLMProxyError,
    RateLimitExceededError,
)
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.traffic_leg import TrafficLeg
from src.core.interfaces.exception_normalizer_interface import IExceptionNormalizer
from src.core.interfaces.planning_phase_manager_interface import IPlanningPhaseManager
from src.core.interfaces.resilience_interface import IResilienceCoordinator
from src.core.interfaces.stream_formatting_interface import IStreamFormattingService
from src.core.interfaces.stream_session_id_resolver_interface import (
    IStreamSessionIdResolver,
)
from src.core.interfaces.usage_tracking_interface import IUsageTrackingService
from src.core.interfaces.usage_tracking_wrapper_interface import IUsageTrackingWrapper
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.services.backend_completion_flow.wire_capture_helper import (
    WireCaptureHelper,
)

logger = logging.getLogger(__name__)


class ResponseHandler:
    """Handles response processing, usage tracking, and error normalization."""

    def __init__(
        self,
        stream_session_id_resolver: IStreamSessionIdResolver,
        stream_formatting_service: IStreamFormattingService,
        usage_tracking_wrapper: IUsageTrackingWrapper,
        exception_normalizer: IExceptionNormalizer,
        planning_phase_manager: IPlanningPhaseManager,
        wire_capture: IWireCapture | None,
        usage_tracking_service: IUsageTrackingService | None,
        resilience_coordinator: IResilienceCoordinator | None,
        wire_capture_helper: WireCaptureHelper,
        backend_factory: Any,  # IBackendFactory
        backend_lifecycle_manager: Any,  # IBackendLifecycleManager
    ):
        """Initialize the response handler."""
        self._stream_session_id_resolver = stream_session_id_resolver
        self._stream_formatting_service = stream_formatting_service
        self._usage_tracking_wrapper = usage_tracking_wrapper
        self._exception_normalizer = exception_normalizer
        self._planning_phase_manager = planning_phase_manager
        self._wire_capture = wire_capture
        self._usage_tracking_service = usage_tracking_service
        self._resilience = resilience_coordinator
        self._wire_capture_helper = wire_capture_helper
        self._backend_factory = backend_factory
        self._backend_lifecycle_manager = backend_lifecycle_manager

    async def calculate_and_record_usage(
        self,
        domain_request: ChatRequest,
        request: ChatRequest,
        backend_type: str,
        effective_model: str,
        session: Any | None,
        session_id_for_backend: str | None,
    ) -> tuple[int, str | None, str | None]:
        """Calculate tokens and record request usage.

        Args:
            domain_request: The transformed request
            request: The original request
            backend_type: The backend name
            effective_model: The model name
            session: Optional session object
            session_id_for_backend: Optional session ID

        Returns:
            Tuple of (outbound_tokens, ctp_record_id, ptb_record_id)
        """
        ctp_record_id = None
        ptb_record_id = None
        outbound_tokens = 0

        try:
            from src.core.utils.usage_recalculation import calculate_outbound_tokens

            outbound_tokens = calculate_outbound_tokens(
                domain_request, model=effective_model
            )

            # Calculate verbatim tokens (from original request)
            verbatim_tokens = 0
            if self._usage_tracking_service:
                verbatim_tokens = calculate_outbound_tokens(
                    request, model=effective_model
                )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Outbound tokens to {backend_type}/{effective_model}: {outbound_tokens} (verbatim: {verbatim_tokens})"
                )

            # Record request usage
            if self._usage_tracking_service:
                try:
                    # Use session.state.proxy_user if available
                    proxy_user = None
                    if (
                        session
                        and hasattr(session, "state")
                        and hasattr(session.state, "proxy_user")
                    ):
                        proxy_user = session.state.proxy_user

                    sid = session_id_for_backend or "unknown"

                    ctp_record_id = await self._usage_tracking_service.record_request(
                        session_id=sid,
                        backend_type=backend_type,
                        model=effective_model,
                        frontend_type="openai",
                        leg=TrafficLeg.CLIENT_TO_PROXY,
                        prompt_tokens=verbatim_tokens,
                        proxy_user=proxy_user,
                    )

                    ptb_record_id = await self._usage_tracking_service.record_request(
                        session_id=sid,
                        backend_type=backend_type,
                        model=effective_model,
                        frontend_type="openai",
                        leg=TrafficLeg.PROXY_TO_BACKEND,
                        prompt_tokens=outbound_tokens,
                        proxy_user=proxy_user,
                    )
                except Exception as e:
                    logger.warning(f"Failed to record request usage: {e}")

        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to calculate outbound tokens or record usage",
                    exc_info=True,
                )

        return outbound_tokens, ctp_record_id, ptb_record_id

    async def wrap_response_for_usage(
        self,
        result: ResponseEnvelope | StreamingResponseEnvelope,
        outbound_tokens: int,
        ctp_record_id: str | None,
        ptb_record_id: str | None,
        start_time: float,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Wrap response with usage tracking.

        Args:
            result: The backend response
            outbound_tokens: Number of outbound tokens
            ctp_record_id: Client-to-proxy record ID
            ptb_record_id: Proxy-to-backend record ID
            start_time: Request start timestamp

        Returns:
            Response with usage tracking applied
        """
        # Store outbound tokens in result metadata for tracking
        if hasattr(result, "metadata") and result.metadata is None:
            result.metadata = {}
        if hasattr(result, "metadata") and isinstance(result.metadata, dict):
            result.metadata["outbound_tokens"] = outbound_tokens

        # Wrap result content for usage tracking
        if (
            isinstance(result, StreamingResponseEnvelope)
            and self._usage_tracking_service
            and (ctp_record_id or ptb_record_id)
        ):
            if result.content is not None:
                result.content = self._usage_tracking_wrapper.wrap_stream_for_usage(
                    result.content,
                    ctp_record_id,
                    ptb_record_id,
                    start_time,
                )
        elif (
            isinstance(result, ResponseEnvelope)
            and self._usage_tracking_service
            and (ctp_record_id or ptb_record_id)
        ):
            try:
                usage = getattr(result, "usage", None)
                if (
                    usage is None
                    and hasattr(result, "metadata")
                    and isinstance(result.metadata, dict)
                ):
                    usage = result.metadata.get("usage")

                if usage:
                    if not isinstance(usage, dict) and hasattr(usage, "model_dump"):
                        usage = usage.model_dump()

                    completion_tokens = usage.get("completion_tokens", 0)
                    duration_ms = (time.time() - start_time) * 1000

                    if ptb_record_id:
                        await self._usage_tracking_service.record_response(
                            record_id=ptb_record_id,
                            completion_tokens=completion_tokens,
                            backend_reported_usage=usage,
                            http_status_code=getattr(result, "status_code", 200),
                            total_duration_ms=duration_ms,
                        )

                    if ctp_record_id:
                        await self._usage_tracking_service.record_response(
                            record_id=ctp_record_id,
                            completion_tokens=completion_tokens,
                            backend_reported_usage=usage,
                            http_status_code=getattr(result, "status_code", 200),
                            total_duration_ms=duration_ms,
                        )
            except Exception as e:
                logger.error(f"Failed to record response usage: {e}", exc_info=True)

        return result

    async def handle_streaming_response(
        self,
        result: StreamingResponseEnvelope,
        backend_type: str,
        effective_model: str,
        context: RequestContext | None,
        request: ChatRequest,
        session_id_for_backend: str | None,
    ) -> StreamingResponseEnvelope:
        """Handle streaming response with wire capture and session ID injection.

        Args:
            result: The streaming response envelope
            backend_type: The backend name
            effective_model: The model name
            context: Optional request context
            request: The request
            session_id_for_backend: Optional session ID

        Returns:
            Wrapped streaming response envelope
        """
        # Get session_id from context for stream correlation
        session_id = getattr(context, "session_id", None)
        session_id = self._stream_session_id_resolver.resolve_stream_session_id(
            session_id, context, request
        )
        if context is not None and not getattr(context, "session_id", None):
            with contextlib.suppress(Exception):
                context.session_id = session_id

        # Wire-capture: capture inbound
        try:
            if self._wire_capture and self._wire_capture.enabled():
                key_name = self._wire_capture_helper.detect_key_name(backend_type)

                if result.content is None:
                    await self._wire_capture.capture_inbound_response(
                        context=context,
                        session_id=session_id,
                        backend=backend_type,
                        model=effective_model,
                        key_name=key_name,
                        response_content=b"",
                    )
                    wrapped_stream = None
                else:
                    # Adapt domain stream to bytes for capture and transport
                    byte_stream = self._stream_formatting_service.stream_as_sse_bytes(
                        result.content
                    )
                    wrapped_stream = self._wire_capture.wrap_inbound_stream(
                        context=context,
                        session_id=session_id,
                        backend=backend_type,
                        model=effective_model,
                        key_name=key_name,
                        stream=byte_stream,  # type: ignore[arg-type]
                    )

                # Convert back to ProcessedResponse stream for adapters
                async def _to_processed_with_capture() -> Any:
                    from src.core.interfaces.response_processor_interface import (
                        ProcessedResponse,
                    )

                    if wrapped_stream is not None:
                        async for b in wrapped_stream:
                            yield ProcessedResponse(
                                content=b,
                                metadata=(
                                    {
                                        "session_id": session_id,
                                        "stream_id": session_id,
                                    }
                                    if session_id
                                    else {}
                                ),
                            )

                    if session_id and self._planning_phase_manager:
                        await self._planning_phase_manager.update_counters(
                            session_id,
                            ProcessedResponse(content="", metadata={}),
                        )

                # Record success for streaming response
                if self._resilience:
                    self._resilience.record_success(backend_type, effective_model)

                return StreamingResponseEnvelope(
                    content=_to_processed_with_capture(),
                    media_type=result.media_type,
                    headers=result.headers,
                    metadata=result.metadata,
                )
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Wire capture (response) failed for backend %s with model %s",
                    backend_type,
                    effective_model,
                    exc_info=True,
                )

        # IMPORTANT: Always wrap streaming responses with session_id for proper
        # tool call buffering, even when wire capture is disabled
        if isinstance(result, StreamingResponseEnvelope):
            original_content = result.content

            async def _inject_session_id() -> Any:
                from src.core.interfaces.response_processor_interface import (
                    ProcessedResponse,
                )

                async for chunk in original_content:  # type: ignore
                    if isinstance(chunk, ProcessedResponse):
                        # Merge session_id into existing metadata
                        metadata = dict(chunk.metadata or {})
                        if session_id and "session_id" not in metadata:
                            metadata["session_id"] = session_id
                        if session_id and "stream_id" not in metadata:
                            metadata["stream_id"] = session_id
                        yield ProcessedResponse(
                            content=chunk.content,
                            metadata=metadata,
                            usage=chunk.usage,
                        )
                    else:
                        # Wrap raw chunk with session_id
                        yield ProcessedResponse(
                            content=chunk,
                            metadata=(
                                {
                                    "session_id": session_id,
                                    "stream_id": session_id,
                                }
                                if session_id
                                else {}
                            ),
                        )

                if session_id and self._planning_phase_manager:
                    await self._planning_phase_manager.update_counters(
                        session_id, ProcessedResponse(content="", metadata={})
                    )

            # Record success for streaming response
            if self._resilience:
                self._resilience.record_success(backend_type, effective_model)

            return StreamingResponseEnvelope(
                content=_inject_session_id(),
                media_type=result.media_type,
                headers=result.headers,
                metadata=result.metadata,
            )

        return result

    async def handle_non_streaming_response(
        self,
        result: ResponseEnvelope,
        backend_type: str,
        effective_model: str,
        session_id_for_backend: str | None,
    ) -> ResponseEnvelope:
        """Handle non-streaming response with usage recording and planning phase updates.

        Args:
            result: The response envelope
            backend_type: The backend name
            effective_model: The model name
            session_id_for_backend: Optional session ID

        Returns:
            The response envelope
        """
        # Record success in resilience coordinator
        if self._resilience:
            self._resilience.record_success(backend_type, effective_model)

        if session_id_for_backend and self._planning_phase_manager:
            await self._planning_phase_manager.update_counters(
                session_id_for_backend, result
            )

        return result

    async def handle_auth_failure(
        self,
        exc: AuthenticationError | HTTPException | BackendError,
        backend: LLMBackend,
        backend_type: str,
        session_id_for_backend: str | None,
    ) -> None:
        """Handle authentication failure with backend lifecycle side effects.

        Args:
            exc: The authentication exception
            backend: The backend instance
            backend_type: The backend name
            session_id_for_backend: Optional session ID

        Raises:
            The original exception after handling
        """
        is_auth_error = False
        auth_message = ""

        if isinstance(exc, AuthenticationError):
            is_auth_error = True
            auth_message = str(exc)
        elif (
            isinstance(exc, HTTPException) and getattr(exc, "status_code", None) == 401
        ):
            is_auth_error = True
            auth_message = str(getattr(exc, "detail", "Unauthorized"))
        elif isinstance(exc, BackendError) and getattr(exc, "status_code", None) == 401:
            is_auth_error = True
            auth_message = getattr(exc, "message", str(exc))

        if is_auth_error and backend.has_static_credentials:
            # Permanent auth failure for static backends (env vars)
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Authentication failed for static backend %s: %s",
                    backend_type,
                    exc,
                )
            backend.mark_auth_invalid(auth_message)
            if hasattr(self._backend_factory, "unregister_backend"):
                self._backend_factory.unregister_backend(backend_type)  # type: ignore[attr-defined]
            self._backend_lifecycle_manager.discard(
                backend_type, session_id_for_backend, reason=auth_message
            )

    async def handle_backend_error(
        self,
        call_exc: Exception,
        backend_type: str,
        effective_model: str,
        context: RequestContext | None,
        request: ChatRequest,
        backend: LLMBackend,
        normalized_exc: Exception | None = None,
    ) -> None:
        """Handle backend error with normalization and wire capture.

        Args:
            call_exc: The exception that occurred
            backend_type: The backend name
            effective_model: The model name
            context: Optional request context
            request: The request
            backend: The backend instance
            normalized_exc: Optional pre-normalized exception (to avoid double normalization)
        """
        # DEBUG: Log that we caught an exception
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "BackendCompletionFlow caught exception from %s: %s (type=%s, status=%s)",
                backend_type,
                call_exc,
                type(call_exc).__name__,
                getattr(call_exc, "status_code", None),
            )

        # Normalize the exception if not already normalized
        if normalized_exc is None:
            normalized_exc = self._exception_normalizer.normalize(
                call_exc, backend_type
            )

        capture_session_id: str | None = None
        if context is not None:
            capture_session_id = getattr(context, "session_id", None)
        if not capture_session_id:
            capture_session_id = getattr(request, "session_id", None)

        # Best-effort wire-capture of error payloads
        try:
            if self._wire_capture and self._wire_capture.enabled():
                error_payload: dict[str, Any]
                if isinstance(normalized_exc, LLMProxyError):
                    error_payload = normalized_exc.to_dict()
                    with contextlib.suppress(Exception):
                        if (
                            isinstance(error_payload.get("error"), dict)
                            and "status_code" not in error_payload["error"]
                        ):
                            error_payload["error"]["status_code"] = getattr(
                                normalized_exc, "status_code", None
                            )
                else:
                    error_payload = {
                        "error": {
                            "message": str(normalized_exc),
                            "type": type(normalized_exc).__name__,
                        }
                    }

                key_name = self._wire_capture_helper.detect_key_name(backend_type)
                await self._wire_capture.capture_inbound_response(
                    context=context,
                    session_id=capture_session_id,
                    backend=backend_type,
                    model=effective_model,
                    key_name=key_name,
                    response_content=error_payload,
                )
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Wire capture (error response) failed for backend %s with model %s",
                    backend_type,
                    effective_model,
                    exc_info=True,
                )

        # Store retry-after in backend instance if this is a rate limit error
        if isinstance(normalized_exc, RateLimitExceededError) and hasattr(
            backend, "set_retry_after"
        ):
            reset_at = getattr(normalized_exc, "reset_at", None)
            if reset_at is not None:
                retry_after_seconds = reset_at - time.time()
                if retry_after_seconds > 0:
                    backend.set_retry_after(retry_after_seconds)
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Backend %s rate limited, cached retry-after for %.1f seconds",
                            backend_type,
                            retry_after_seconds,
                        )
