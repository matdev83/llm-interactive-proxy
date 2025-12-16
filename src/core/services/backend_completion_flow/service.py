"""Backend completion flow orchestration service."""

from __future__ import annotations

import logging
import time
from typing import Any

from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    LLMProxyError,
    RateLimitExceededError,
)
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_completion_collaborators import (
    IBackendAvailabilityChecker,
    IBackendInvoker,
    IBackendRequestPreparer,
    ICompletionSessionResolver,
    IFailureRecoveryExecutor,
    IUsageAccountingOrchestrator,
    IWireCaptureOrchestrator,
)
from src.core.interfaces.backend_completion_flow_interface import (
    IBackendCompletionFlow,
)
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider
from src.core.interfaces.backend_factory_interface import IBackendFactory
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.backend_model_resolver_interface import (
    IBackendModelResolver,
)
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.exception_normalizer_interface import IExceptionNormalizer
from src.core.interfaces.failover_interface import (
    IFailoverCoordinator,
)
from src.core.interfaces.failover_planner_interface import IFailoverPlanner
from src.core.interfaces.failure_strategy_interface import (
    IFailureHandlingStrategy,
)
from src.core.interfaces.planning_phase_manager_interface import IPlanningPhaseManager
from src.core.interfaces.reasoning_config_applicator_interface import (
    IReasoningConfigApplicator,
)
from src.core.interfaces.resilience_interface import IResilienceCoordinator
from src.core.interfaces.session_service_interface import ISessionService
from src.core.interfaces.stream_formatting_interface import IStreamFormattingService
from src.core.interfaces.stream_session_id_resolver_interface import (
    IStreamSessionIdResolver,
)
from src.core.interfaces.uri_parameter_applicator_interface import (
    IURIParameterApplicator,
)
from src.core.interfaces.usage_tracking_interface import IUsageTrackingService
from src.core.interfaces.usage_tracking_wrapper_interface import IUsageTrackingWrapper
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.services.backend_routing_service import BackendRoutingService

logger = logging.getLogger(__name__)


class BackendCompletionFlow(IBackendCompletionFlow):
    """Orchestrates backend completion requests with failover, retry, and observability.

    This coordinator delegates substantial logic to focused collaborators:
    - BackendAvailabilityChecker: Availability gating (disabled backends, resilience checks)
    - CompletionSessionResolver: Session resolution and per-session backend selection
    - BackendRequestPreparer: Request preparation, config application, and target synchronization
    - BackendManager: Backend instance acquisition and lifecycle management
    - WireCaptureOrchestrator: Wire capture orchestration (outbound/inbound/errors)
    - UsageAccountingOrchestrator: Usage tracking, response wrapping, and accounting
    - FailureRecoveryExecutor: Failure recovery, retry, and failover execution

    The orchestrator owns flow ordering and shared context only. All substantial logic
    is delegated to collaborators to maintain clear boundaries and improve testability.

    Raises:
        BackendError: If backend call fails and recovery is not possible
        RateLimitExceededError: If backend is rate limited
        AuthenticationError: If authentication fails
    """

    def __init__(
        self,
        backend_model_resolver: IBackendModelResolver,
        stream_session_id_resolver: IStreamSessionIdResolver,
        failover_planner: IFailoverPlanner,
        session_service: ISessionService,
        backend_lifecycle_manager: IBackendLifecycleManager,
        backend_config_service: IBackendConfigProvider,
        reasoning_config_applicator: IReasoningConfigApplicator,
        uri_parameter_applicator: IURIParameterApplicator,
        stream_formatting_service: IStreamFormattingService,
        usage_tracking_wrapper: IUsageTrackingWrapper,
        exception_normalizer: IExceptionNormalizer,
        planning_phase_manager: IPlanningPhaseManager,
        backend_factory: IBackendFactory,
        config: IConfig,
        app_state: IApplicationState,
        failover_coordinator: IFailoverCoordinator,
        # Required collaborators (formerly optional/injected)
        availability_checker: IBackendAvailabilityChecker,
        request_preparer_collaborator: IBackendRequestPreparer,
        session_resolver: ICompletionSessionResolver,
        failover_executor: IFailureRecoveryExecutor,
        wire_capture_orchestrator: IWireCaptureOrchestrator,
        usage_accounting_orchestrator: IUsageAccountingOrchestrator,
        backend_invoker: IBackendInvoker,
        # Legacy optional args (deprecated, kept for signature compatibility)
        # These are passed from DI but not used in the implementation.
        # TODO: Remove in next major version after updating all call sites.
        wire_capture: IWireCapture | None = None,
        usage_tracking_service: IUsageTrackingService | None = None,
        resilience_coordinator: IResilienceCoordinator | None = None,
        failure_handling_strategy: IFailureHandlingStrategy | None = None,
        routing_service: BackendRoutingService | None = None,
        failover_routes: dict[str, dict[str, Any]] | None = None,
    ):
        """Initialize the completion flow orchestrator."""
        self._availability_checker = availability_checker
        self._request_preparer = request_preparer_collaborator
        self._session_resolver = session_resolver
        self._failover_executor = failover_executor
        self._wire_capture_orchestrator = wire_capture_orchestrator
        self._usage_accounting = usage_accounting_orchestrator
        self._backend_invoker = backend_invoker
        self._backend_lifecycle_manager = backend_lifecycle_manager

        # Store dependencies needed for local logic
        self._resilience = resilience_coordinator
        self._exception_normalizer = exception_normalizer
        self._stream_formatting_service = stream_formatting_service

    async def call_completion(
        self,
        request: ChatRequest,
        stream: bool = False,
        allow_failover: bool = True,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute completion orchestration with failover, retry, and observability."""
        # Step 1: Prepare request (resolve target + synchronize)
        (
            backend_type,
            effective_model,
            uri_params,
        ) = await self._request_preparer.prepare_request(request, context)
        request = self._request_preparer.synchronize_request_with_target(
            request, backend_type, effective_model
        )

        # Step 2: Check if complex failover applies
        if allow_failover and await self._failover_executor.check_complex_failover(
            request, effective_model, backend_type, stream, context
        ):
            # Complex failover handled, return result
            return await self._failover_executor.execute_complex_failover(
                request,
                effective_model,
                backend_type,
                stream,
                self.call_completion,
                context,
            )

        # Step 3: Check backend availability (disabled + resilience)
        await self._availability_checker.check_backend_availability(
            backend_type, effective_model, allow_failover
        )

        # Step 4: Initialize failure strategy tracking
        start_time = time.time()
        attempted_backends: list[str] = []
        current_backend = backend_type
        content_started = False

        try:
            # Step 5: Resolve session
            (
                session,
                session_id_for_backend,
            ) = await self._session_resolver.resolve_session(context, request)

            # Step 6: Acquire backend instance
            backend = await self._backend_invoker.acquire_backend(
                backend_type, session_id_for_backend
            )

            # Step 7: Prepare backend request (configs + URI params)
            domain_request = await self._request_preparer.prepare_backend_request(
                request, backend_type, session, uri_params
            )

            # Step 8: Prepare wire capture context (identity + backend config)
            identity = (
                await self._wire_capture_orchestrator.prepare_wire_capture_context(
                    backend_type, session
                )
            )

            # Step 9: Execute backend call (with wire capture + usage tracking)
            try:
                # Wire-capture: capture outbound payload pre-call (best-effort)
                await self._wire_capture_orchestrator.capture_wire_outbound(
                    backend_type=backend_type,
                    effective_model=effective_model,
                    domain_request=domain_request,
                    context=context,
                )

                # Prepare backend call kwargs
                backend_call_kwargs = self._request_preparer.prepare_backend_kwargs(
                    session_id_for_backend=session_id_for_backend,
                    session=session,
                    context=context,
                    backend_type=backend_type,
                )

                # Calculate outbound tokens and record usage
                (
                    outbound_tokens,
                    ctp_record_id,
                    ptb_record_id,
                ) = await self._usage_accounting.calculate_and_record_usage(
                    domain_request=domain_request,
                    request=request,
                    backend_type=backend_type,
                    effective_model=effective_model,
                    session=session,
                    session_id_for_backend=session_id_for_backend,
                )

                # Execute the backend call
                result: ResponseEnvelope | StreamingResponseEnvelope = (
                    await backend.chat_completions(
                        request_data=domain_request,
                        processed_messages=request.messages,
                        effective_model=effective_model,
                        identity=identity,
                        **backend_call_kwargs,
                    )
                )

                # Wrap result for usage tracking
                result = await self._usage_accounting.wrap_response_for_usage(
                    result=result,
                    outbound_tokens=outbound_tokens,
                    ctp_record_id=ctp_record_id,
                    ptb_record_id=ptb_record_id,
                    start_time=start_time,
                )

                # Step 10: Handle streaming response (wire capture + session ID injection)
                if isinstance(result, StreamingResponseEnvelope):
                    # Wire-capture: capture inbound stream
                    key_name = self._wire_capture_orchestrator.detect_key_name(
                        backend_type
                    )
                    session_id = getattr(context, "session_id", None)

                    if result.content is not None:
                        # Adapt domain stream to bytes for capture
                        byte_stream = (
                            self._stream_formatting_service.stream_as_sse_bytes(
                                result.content
                            )
                        )
                        wrapped_stream = (
                            self._wire_capture_orchestrator.wrap_inbound_stream(
                                context=context,
                                session_id=session_id,
                                backend_type=backend_type,
                                effective_model=effective_model,
                                key_name=key_name,
                                stream=byte_stream,
                            )
                        )

                        # Convert back to ProcessedResponse stream for adapters
                        async def _to_processed_with_capture() -> Any:
                            from src.core.interfaces.response_processor_interface import (
                                ProcessedResponse,
                            )

                            async for b in wrapped_stream:
                                yield ProcessedResponse(content=b, metadata={})

                        result.content = _to_processed_with_capture()

                    return await self._usage_accounting.handle_streaming_response(
                        result=result,
                        backend_type=backend_type,
                        effective_model=effective_model,
                        context=context,
                        request=domain_request,
                        session_id_for_backend=session_id_for_backend,
                    )

                # Step 11: Handle non-streaming response
                # Wire-capture: capture inbound response
                key_name = self._wire_capture_orchestrator.detect_key_name(backend_type)
                # Serialize content for capture (best effort)
                response_content: Any = result
                if hasattr(result, "model_dump"):
                    response_content = result.model_dump()
                elif hasattr(result, "__dict__"):
                    response_content = result.__dict__

                await self._wire_capture_orchestrator.capture_inbound_response(
                    context=context,
                    session_id=getattr(context, "session_id", None),
                    backend_type=backend_type,
                    effective_model=effective_model,
                    key_name=key_name,
                    response_content=response_content,
                )

                return await self._usage_accounting.handle_non_streaming_response(
                    result=result,
                    backend_type=backend_type,
                    effective_model=effective_model,
                    session_id_for_backend=session_id_for_backend,
                )

            except Exception as call_exc:
                # Normalize the exception immediately for consistent handling
                normalized_exc = self._exception_normalizer.normalize(
                    call_exc, backend_type
                )
                # Safety check: ensure normalized_exc is actually an Exception
                if not isinstance(normalized_exc, Exception):
                    normalized_exc = BackendError(
                        message=f"Backend call failed: {call_exc!s}",
                        backend_name=backend_type,
                    )
                    normalized_exc.__cause__ = call_exc

                # Check if this is an authentication failure first
                is_auth_failure = False
                if isinstance(normalized_exc, AuthenticationError) or (
                    hasattr(normalized_exc, "status_code")
                    and getattr(normalized_exc, "status_code", None) == 401
                ):
                    is_auth_failure = True

                if is_auth_failure:
                    # Handle authentication failures with backend lifecycle side effects
                    await self._usage_accounting.handle_auth_failure(
                        normalized_exc,
                        backend,
                        backend_type,
                        session_id_for_backend,
                    )
                    raise normalized_exc

                # Handle backend error (wire capture + usage/resilience updates)
                # 1. Wire capture error
                key_name = self._wire_capture_orchestrator.detect_key_name(backend_type)
                error_payload: dict[str, Any]
                if isinstance(normalized_exc, LLMProxyError):
                    error_payload = normalized_exc.to_dict()
                    # Ensure status code is present if available
                    import contextlib

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

                await self._wire_capture_orchestrator.capture_inbound_response(
                    context=context,
                    session_id=getattr(context, "session_id", None),
                    backend_type=backend_type,
                    effective_model=effective_model,
                    key_name=key_name,
                    response_content=error_payload,
                )

                # 2. Update resilience/usage via accounting collaborator
                await self._usage_accounting.handle_backend_error(
                    call_exc=call_exc,
                    backend_type=current_backend,
                    effective_model=effective_model,
                    context=context,
                    request=request,
                    backend=backend,
                    normalized_exc=normalized_exc,
                )

                # Step 13: Apply failure recovery (retry/failover)
                if allow_failover:
                    return await self._failover_executor.apply_failure_recovery(
                        error=normalized_exc,
                        model=effective_model,
                        backend_type=current_backend,
                        attempted_backends=attempted_backends,
                        start_time=start_time,
                        is_streaming=stream,
                        content_started=content_started,
                        request=request,
                        context=context,
                        call_completion_callback=self.call_completion,
                    )

                # No failover allowed, raise the normalized error
                raise normalized_exc

        except (
            BackendError,
            RateLimitExceededError,
            LLMProxyError,
            AuthenticationError,
        ) as exc:
            # Record failure in resilience coordinator (handles cooldown/backoff)
            if self._resilience:
                self._resilience.record_failure(backend_type, effective_model, exc)
            # Propagate expected exceptions as-is
            raise
        except Exception as exc:
            # Use duck typing to detect transport exceptions without importing FastAPI/Starlette
            # This preserves layer boundaries while allowing proper error handling
            if hasattr(exc, "status_code") and not isinstance(exc, BackendError):
                # Don't record failure for generic HTTP exceptions (likely client errors)
                # But do propagate them
                raise
            # Otherwise fall through to generic exception handling
            raise BackendError(
                message=f"Backend call failed: {exc!s}",
                backend_name=backend_type,
            ) from exc
