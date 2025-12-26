"""Usage accounting orchestration collaborator."""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any

from src.connectors.base import LLMBackend
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    RateLimitExceededError,
)
from src.core.domain.chat import CanonicalChatRequest, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.traffic_leg import TrafficLeg
from src.core.domain.usage_summary import UsageSummary
from src.core.interfaces.backend_completion_collaborators import (
    IUsageAccountingOrchestrator,
    IWireCaptureOrchestrator,
)
from src.core.interfaces.backend_factory_interface import IBackendFactory
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.domain_entities_interface import ISession
from src.core.interfaces.planning_phase_manager_interface import IPlanningPhaseManager
from src.core.interfaces.resilience_interface import IResilienceCoordinator
from src.core.interfaces.stream_session_id_resolver_interface import (
    IStreamSessionIdResolver,
)
from src.core.interfaces.usage_normalization_service_interface import (
    IUsageNormalizationService,
)
from src.core.interfaces.usage_tracking_interface import IUsageTrackingService
from src.core.interfaces.usage_tracking_wrapper_interface import IUsageTrackingWrapper
from src.core.utils.usage_recalculation import calculate_outbound_tokens

logger = logging.getLogger(__name__)


def _to_usage_summary(usage: Any) -> UsageSummary | None:
    """Convert usage from various formats to UsageSummary.

    Args:
        usage: Usage data in various formats (dict, UsageSummary, StreamingUsage, etc.)

    Returns:
        UsageSummary instance or None
    """
    if usage is None:
        return None
    if isinstance(usage, UsageSummary):
        return usage
    if isinstance(usage, dict):
        return UsageSummary.from_dict(usage)
    # Try to extract dict from Pydantic models
    if hasattr(usage, "model_dump"):
        return UsageSummary.from_dict(usage.model_dump())
    if hasattr(usage, "to_dict"):
        return UsageSummary.from_dict(usage.to_dict())
    if hasattr(usage, "__dict__"):
        return UsageSummary.from_dict(usage.__dict__)
    return None


class UsageAccountingOrchestrator(IUsageAccountingOrchestrator):
    """Handles usage accounting, response wrapping, and lifecycle updates."""

    def __init__(
        self,
        usage_tracking_service: IUsageTrackingService | None,
        usage_tracking_wrapper: IUsageTrackingWrapper,
        stream_session_id_resolver: IStreamSessionIdResolver,
        planning_phase_manager: IPlanningPhaseManager,
        resilience_coordinator: IResilienceCoordinator | None,
        backend_factory: IBackendFactory | None = None,
        backend_lifecycle_manager: IBackendLifecycleManager | None = None,
        usage_normalization_service: IUsageNormalizationService | None = None,
        wire_capture_orchestrator: IWireCaptureOrchestrator | None = None,
    ):
        """Initialize the usage accounting orchestrator."""
        self._usage_tracking_service = usage_tracking_service
        self._usage_tracking_wrapper = usage_tracking_wrapper
        self._stream_session_id_resolver = stream_session_id_resolver
        self._planning_phase_manager = planning_phase_manager
        self._resilience = resilience_coordinator
        self._backend_factory = backend_factory
        self._backend_lifecycle_manager = backend_lifecycle_manager
        self._usage_normalization_service = usage_normalization_service
        self._wire_capture_orchestrator = wire_capture_orchestrator

    async def calculate_and_record_usage(
        self,
        domain_request: ChatRequest,
        request: ChatRequest,
        backend_type: str,
        effective_model: str,
        session: ISession | None,
        session_id_for_backend: str | None,
    ) -> tuple[int, str | None, str | None]:
        """Calculate tokens and record request usage."""
        ctp_record_id = None
        ptb_record_id = None
        outbound_tokens = 0

        try:
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
                    if logger.isEnabledFor(logging.WARNING):
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
        context: RequestContext | None = None,
        backend_type: str | None = None,
        effective_model: str | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Wrap response with usage tracking."""
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
                    # Convert UsageSummary to dict if needed
                    if hasattr(usage, "to_dict"):
                        usage_dict = usage.to_dict()
                    elif hasattr(usage, "model_dump"):
                        usage_dict = usage.model_dump()
                    elif isinstance(usage, dict):
                        usage_dict = usage
                    else:
                        usage_dict = {}

                    completion_tokens = usage_dict.get("completion_tokens", 0)
                    duration_ms = (time.time() - start_time) * 1000

                    if ptb_record_id:
                        await self._usage_tracking_service.record_response(
                            record_id=ptb_record_id,
                            completion_tokens=completion_tokens,
                            backend_reported_usage=usage_dict,
                            http_status_code=getattr(result, "status_code", 200),
                            total_duration_ms=duration_ms,
                        )

                    if ctp_record_id:
                        await self._usage_tracking_service.record_response(
                            record_id=ctp_record_id,
                            completion_tokens=completion_tokens,
                            backend_reported_usage=usage_dict,
                            http_status_code=getattr(result, "status_code", 200),
                            total_duration_ms=duration_ms,
                        )
            except Exception as e:
                logger.error(f"Failed to record response usage: {e}", exc_info=True)

        # Build canonical usage for non-streaming responses
        if (
            isinstance(result, ResponseEnvelope)
            and self._usage_normalization_service
            and context is not None
        ):
            try:
                from src.core.domain.usage_canonical_record import (
                    UsageCompletionOutcome,
                )
                from src.core.domain.usage_normalization_context import (
                    UsageNormalizationContext,
                )
                from src.core.domain.usage_payload import UsagePayload

                # Extract usage from envelope
                usage_summary = getattr(result, "usage", None)
                raw_usage = None
                if usage_summary is None and hasattr(result, "metadata"):
                    metadata = result.metadata
                    if isinstance(metadata, dict):
                        usage_data = metadata.get("usage")
                        if usage_data:
                            if isinstance(usage_data, dict):
                                raw_usage = UsagePayload(payload=usage_data)
                            else:
                                usage_summary = _to_usage_summary(usage_data)

                # Build normalization context
                norm_context = UsageNormalizationContext.from_request_context(
                    context,
                    is_streaming=False,
                    completion_outcome=UsageCompletionOutcome.complete,
                )

                # Override backend_type and model if provided
                if backend_type:
                    norm_context.backend_type = backend_type
                if effective_model:
                    norm_context.model = effective_model

                # Build canonical usage record
                canonical_usage = (
                    await self._usage_normalization_service.build_canonical_record(
                        context=norm_context,
                        usage=usage_summary,
                        raw_usage=raw_usage,
                    )
                )

                # Attach canonical usage to envelope
                result.canonical_usage = canonical_usage
            except Exception as e:
                logger.warning(
                    f"Failed to build canonical usage for non-streaming response: {e}",
                    exc_info=True,
                )

        return result

    async def handle_streaming_response(
        self,
        result: StreamingResponseEnvelope,
        backend_type: str,
        effective_model: str,
        context: RequestContext | None,
        request: CanonicalChatRequest,
        session_id_for_backend: str | None,
        key_name: str | None = None,
    ) -> StreamingResponseEnvelope:
        """Handle streaming response with session ID injection and phase updates."""
        # Get session_id from context for stream correlation
        session_id = getattr(context, "session_id", None)
        session_id = self._stream_session_id_resolver.resolve_stream_session_id(
            session_id, context, request
        )
        if context is not None and not getattr(context, "session_id", None):
            with contextlib.suppress(Exception):
                context.session_id = session_id

        # Wrap with session_id injection and canonical usage tracking
        original_content = result.content

        async def _inject_session_id_and_track_usage() -> Any:
            from src.core.domain.usage_canonical_record import (
                UsageCompletionOutcome,
            )
            from src.core.domain.usage_normalization_context import (
                UsageNormalizationContext,
            )
            from src.core.domain.usage_payload import UsagePayload
            from src.core.interfaces.response_processor_interface import (
                ProcessedResponse,
            )

            accumulated_usage = None
            completion_outcome: UsageCompletionOutcome | None = None
            error_classification: str | None = None

            try:
                if original_content:
                    async for chunk in original_content:  # type: ignore
                        if isinstance(chunk, ProcessedResponse):
                            # Merge session_id into existing metadata
                            metadata = dict(chunk.metadata or {})
                            if session_id and "session_id" not in metadata:
                                metadata["session_id"] = session_id
                            if session_id and "stream_id" not in metadata:
                                metadata["stream_id"] = session_id

                            # Track usage from chunks
                            if chunk.usage:
                                accumulated_usage = _to_usage_summary(chunk.usage)

                            # Check for error metadata (take precedence over exception-based classification)
                            if isinstance(metadata, dict):
                                error_info = metadata.get("error")
                                if error_info and isinstance(error_info, dict):
                                    error_type = error_info.get("type", "")
                                    if isinstance(error_type, str):
                                        error_type_lower = error_type.lower()
                                        if "timeout" in error_type_lower:
                                            error_classification = "timeout"
                                        elif (
                                            "backenderror" in error_type_lower
                                            or "backend_error" in error_type_lower
                                        ):
                                            error_classification = "backend_error"
                                        elif (
                                            "connectionerror" in error_type_lower
                                            or "connection_error" in error_type_lower
                                        ):
                                            error_classification = "connection_error"

                            yield ProcessedResponse(
                                content=chunk.content,
                                metadata=metadata,
                                usage=_to_usage_summary(chunk.usage),
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

                # Stream completed successfully
                completion_outcome = UsageCompletionOutcome.complete
            except GeneratorExit:
                # Client disconnected - this is expected
                completion_outcome = UsageCompletionOutcome.incomplete
                if context and context.processing_context:
                    if context.processing_context.values is None:
                        from src.core.domain.request_context import ProcessingContext

                        context.processing_context = ProcessingContext(values={})
                    context.processing_context.values["cancel_reason"] = (
                        "client_disconnect"
                    )
                raise
            except Exception as e:
                # Stream error occurred
                completion_outcome = UsageCompletionOutcome.incomplete
                # Classify error (only if not already classified from metadata)
                if error_classification is None:
                    from src.core.common.exceptions import (
                        APIConnectionError,
                        APITimeoutError,
                        BackendError,
                    )

                    if isinstance(e, APITimeoutError):
                        error_classification = "timeout"
                    elif isinstance(e, BackendError):
                        error_classification = "backend_error"
                    elif isinstance(e, APIConnectionError):
                        error_classification = "connection_error"
                    else:
                        error_classification = "unknown"
                raise
            finally:
                # Build canonical usage when stream completes
                if (
                    self._usage_normalization_service
                    and context is not None
                    and completion_outcome is not None
                ):
                    try:
                        # Build normalization context (cancel_reason will be extracted from context)
                        norm_context = UsageNormalizationContext.from_request_context(
                            context,
                            is_streaming=True,
                            completion_outcome=completion_outcome,
                            error_classification=error_classification,
                        )

                        # Override backend_type and model
                        norm_context.backend_type = backend_type
                        norm_context.model = effective_model

                        # Extract raw usage if available
                        raw_usage = None
                        if accumulated_usage is None and hasattr(result, "metadata"):
                            result_metadata = result.metadata
                            if isinstance(result_metadata, dict):
                                usage_data = result_metadata.get("usage")
                                if usage_data and isinstance(usage_data, dict):
                                    raw_usage = UsagePayload(payload=usage_data)

                        # Build canonical usage record
                        canonical_usage = await self._usage_normalization_service.build_canonical_record(
                            context=norm_context,
                            usage=accumulated_usage,
                            raw_usage=raw_usage,
                        )

                        # Attach canonical usage to envelope
                        # Set canonical_usage directly on envelope (primary location)
                        result.canonical_usage = canonical_usage

                        # Capture canonical usage to wire capture (streaming completion)
                        if self._wire_capture_orchestrator is not None:
                            await self._wire_capture_orchestrator.capture_stream_completion(
                                context=context,
                                session_id=session_id,
                                backend_type=backend_type,
                                effective_model=effective_model,
                                key_name=key_name,
                                canonical_usage=canonical_usage,
                            )
                    except Exception as e:
                        logger.warning(
                            f"Failed to build canonical usage for streaming response: {e}",
                            exc_info=True,
                        )

            if session_id and self._planning_phase_manager:
                await self._planning_phase_manager.update_counters(
                    session_id, ProcessedResponse(content="", metadata={})
                )

        # Record success for streaming response
        if self._resilience:
            self._resilience.record_success(backend_type, effective_model)

        # Modify the original result envelope's content and return it
        # This ensures canonical_usage set in the finally block is on the returned envelope
        # Note: canonical_usage will be None initially but set asynchronously when stream completes
        result.content = _inject_session_id_and_track_usage()
        return result

    async def handle_non_streaming_response(
        self,
        result: ResponseEnvelope,
        backend_type: str,
        effective_model: str,
        session_id_for_backend: str | None,
    ) -> ResponseEnvelope:
        """Handle non-streaming response with success recording and phase updates."""
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
        exc: Exception,
        backend: LLMBackend,
        backend_type: str,
        session_id_for_backend: str | None,
    ) -> None:
        """Handle authentication failure with backend lifecycle side effects."""
        if not self._backend_lifecycle_manager or not self._backend_factory:
            return

        is_auth_error = False
        auth_message = ""

        if isinstance(exc, AuthenticationError):
            is_auth_error = True
            auth_message = str(exc)
        elif hasattr(exc, "status_code") and getattr(exc, "status_code", None) == 401:
            # Duck typing for transport exceptions or backend errors
            is_auth_error = True
            if hasattr(exc, "detail"):
                auth_message = str(exc.detail)
            elif hasattr(exc, "message"):
                auth_message = str(exc.message)
            else:
                auth_message = str(exc)
        elif isinstance(exc, BackendError) and getattr(exc, "status_code", None) == 401:
            is_auth_error = True
            auth_message = getattr(exc, "message", str(exc))

        if (
            is_auth_error
            and hasattr(backend, "has_static_credentials")
            and backend.has_static_credentials
        ):
            # Permanent auth failure for static backends (env vars)
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Authentication failed for static backend %s: %s",
                    backend_type,
                    exc,
                )
            if hasattr(backend, "mark_auth_invalid"):
                backend.mark_auth_invalid(auth_message)

            if hasattr(self._backend_factory, "unregister_backend"):
                self._backend_factory.unregister_backend(backend_type)

            self._backend_lifecycle_manager.discard(
                backend_type, session_id_for_backend, reason=auth_message
            )

    async def handle_backend_error(
        self,
        call_exc: Exception,
        backend_type: str,
        effective_model: str,
        context: RequestContext | None,
        request: CanonicalChatRequest,
        backend: LLMBackend,
        normalized_exc: Exception | None = None,
    ) -> None:
        """Handle backend error (resilience updates)."""
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
