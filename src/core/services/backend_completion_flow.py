"""Backend completion flow orchestration service.

This service orchestrates the execution of chat completion requests, including:
- Target resolution (backend/model selection)
- Backend initialization and health checks
- Configuration application (reasoning, backend, URI parameters)
- Wire capture integration (outbound/inbound)
- Usage tracking (verbatim and transformed tokens)
- Failure handling (retry, failover)
- Streaming response management
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any, cast

from fastapi import HTTPException

from src.connectors.base import LLMBackend
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    LLMProxyError,
    RateLimitExceededError,
)
from src.core.config.app_config import AppConfig
from src.core.config.config_loader import _collect_api_keys
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.traffic_leg import TrafficLeg
from src.core.interfaces.application_state_interface import IApplicationState
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
    FailureDecision,
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
    """Orchestrates backend completion requests with failover, retry, and observability."""

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
        wire_capture: IWireCapture | None = None,
        usage_tracking_service: IUsageTrackingService | None = None,
        resilience_coordinator: IResilienceCoordinator | None = None,
        failure_handling_strategy: IFailureHandlingStrategy | None = None,
        routing_service: BackendRoutingService | None = None,
        failover_routes: dict[str, dict[str, Any]] | None = None,
        parent_service: Any | None = None,  # For backward compatibility with tests
    ):
        """Initialize the completion flow orchestrator.

        Args:
            backend_model_resolver: Resolves target backend and model
            stream_session_id_resolver: Resolves stable session IDs for streaming
            failover_planner: Plans failover sequences
            session_service: Session management service
            backend_lifecycle_manager: Manages backend lifecycle
            backend_config_service: Provides backend configurations
            reasoning_config_applicator: Applies reasoning configs
            uri_parameter_applicator: Applies URI parameters
            stream_formatting_service: Formats streams as SSE
            usage_tracking_wrapper: Wraps streams for usage tracking
            exception_normalizer: Normalizes exceptions
            planning_phase_manager: Manages planning phase counters
            backend_factory: Factory for backend creation
            config: Application configuration
            app_state: Application state
            failover_coordinator: Coordinates failover
            wire_capture: Optional wire capture service
            usage_tracking_service: Optional usage tracking service
            resilience_coordinator: Optional resilience coordinator
            failure_handling_strategy: Optional failure handling strategy
            routing_service: Optional routing service
            failover_routes: Optional failover routes configuration
        """
        self._backend_model_resolver = backend_model_resolver
        self._stream_session_id_resolver = stream_session_id_resolver
        self._failover_planner = failover_planner
        self._session_service = session_service
        self._backend_lifecycle_manager = backend_lifecycle_manager
        self._backend_config_service = backend_config_service
        self._reasoning_config_applicator = reasoning_config_applicator
        self._uri_parameter_applicator = uri_parameter_applicator
        self._stream_formatting_service = stream_formatting_service
        self._usage_tracking_wrapper = usage_tracking_wrapper
        self._exception_normalizer = exception_normalizer
        self._planning_phase_manager = planning_phase_manager
        self._backend_factory = backend_factory
        self._config = config
        self._app_state = app_state
        self._failover_coordinator = failover_coordinator
        self._wire_capture = wire_capture
        self._usage_tracking_service = usage_tracking_service
        self._resilience = resilience_coordinator
        self._failure_strategy = failure_handling_strategy
        self._routing_service = routing_service
        self._failover_routes = failover_routes or {}
        self._parent_service = parent_service  # For test compatibility

    async def call_completion(
        self,
        request: ChatRequest,
        stream: bool = False,
        allow_failover: bool = True,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute completion orchestration with failover, retry, and observability.

        Args:
            request: The chat completion request
            stream: Whether to stream the response
            allow_failover: Whether to allow failover to alternative backends
            context: Optional request context for tracking and metadata

        Returns:
            Either a complete response or a streaming response envelope

        Raises:
            BackendError: If the completion request fails
            RateLimitExceededError: If rate limits are exceeded
        """
        # Step 1: Prepare request (resolve target + synchronize)
        backend_type, effective_model, uri_params = await self._prepare_request(
            request, context
        )
        request = self._synchronize_request_with_target(
            request, backend_type, effective_model
        )

        # Step 2: Check if complex failover applies
        if allow_failover and await self._check_complex_failover(
            request, effective_model, backend_type, stream, context
        ):
            # Complex failover handled, return result
            return await self._execute_complex_failover(
                request, effective_model, backend_type, stream, context
            )

        # Step 3: Check backend availability (disabled + resilience)
        await self._check_backend_availability(
            backend_type, effective_model, allow_failover
        )

        # Step 4: Initialize failure strategy tracking
        start_time = time.time()
        attempted_backends: list[str] = []
        current_backend = backend_type
        content_started = False

        try:
            # Step 5: Resolve session
            session, session_id_for_backend = await self._resolve_session(
                context, request
            )

            # Step 6: Acquire backend instance
            backend = await self._acquire_backend(backend_type, session_id_for_backend)

            # Step 7: Prepare backend request (configs + URI params)
            domain_request = await self._prepare_backend_request(
                request, backend_type, session, uri_params
            )

            # Step 8: Prepare wire capture context (identity + backend config)
            identity = await self._prepare_wire_capture_context(backend_type, session)

            # Step 9: Execute backend call (with wire capture + usage tracking)
            try:
                result = await self._execute_backend_call(
                    backend=backend,
                    backend_type=backend_type,
                    effective_model=effective_model,
                    domain_request=domain_request,
                    request=request,
                    identity=identity,
                    session=session,
                    session_id_for_backend=session_id_for_backend,
                    context=context,
                    start_time=start_time,
                )

                # Step 10: Handle streaming response (wire capture + session ID injection)
                if isinstance(result, StreamingResponseEnvelope):
                    return await self._handle_streaming_response(
                        result=result,
                        backend_type=backend_type,
                        effective_model=effective_model,
                        context=context,
                        request=domain_request,
                        session_id_for_backend=session_id_for_backend,
                    )

                # Step 11: Handle non-streaming response (usage recording)
                return await self._handle_non_streaming_response(
                    result=result,
                    backend_type=backend_type,
                    effective_model=effective_model,
                    session_id_for_backend=session_id_for_backend,
                )

            except Exception as call_exc:
                # Check if this is an authentication failure first
                is_auth_failure = False
                if (
                    isinstance(call_exc, AuthenticationError)
                    or isinstance(call_exc, HTTPException)
                    and getattr(call_exc, "status_code", None) == 401
                    or isinstance(call_exc, BackendError)
                    and getattr(call_exc, "status_code", None) == 401
                ):
                    is_auth_failure = True

                if is_auth_failure:
                    # Handle authentication failures with backend lifecycle side effects
                    await self._handle_auth_failure(
                        call_exc,  # type: ignore[arg-type]
                        backend,
                        backend_type,
                        session_id_for_backend,
                    )
                    raise
                # Step 12: Handle backend error (normalization + wire capture)
                # Normalize the exception first so we can use it when raising
                normalized_exc = self._exception_normalizer.normalize(
                    call_exc, current_backend
                )
                await self._handle_backend_error(
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
                    return await self._apply_failure_recovery(
                        error=normalized_exc,
                        model=effective_model,
                        backend_type=current_backend,
                        attempted_backends=attempted_backends,
                        start_time=start_time,
                        is_streaming=stream,
                        content_started=content_started,
                        request=request,
                        context=context,
                    )

                # No failover allowed, raise the normalized error
                if isinstance(
                    normalized_exc,
                    BackendError | RateLimitExceededError | LLMProxyError,
                ):
                    raise normalized_exc
                raise BackendError(
                    message=f"Backend call failed: {call_exc!s}",
                    backend_name=current_backend,
                ) from call_exc

        except (
            BackendError,
            RateLimitExceededError,
            LLMProxyError,
            AuthenticationError,
            HTTPException,
        ) as exc:
            # Record failure in resilience coordinator (handles cooldown/backoff)
            # Skip recording for HTTPException since it might be 4xx/5xx errors
            if self._resilience and not isinstance(exc, HTTPException):
                self._resilience.record_failure(backend_type, effective_model, exc)
            # Propagate expected exceptions as-is
            raise
        except Exception as e:
            # Catch any other unexpected exceptions and wrap them
            raise BackendError(
                message=f"An unexpected error occurred during backend call to {backend_type}: {e!s}",
                backend_name=backend_type,
            ) from e

    async def _prepare_request(
        self, request: ChatRequest, context: RequestContext | None
    ) -> tuple[str, str, dict[str, Any]]:
        """Resolve backend type, effective model, and URI parameters.

        Args:
            request: The chat completion request
            context: Optional request context

        Returns:
            Tuple of (backend_type, effective_model, uri_params)
        """
        resolved = await self._backend_model_resolver.resolve_target(request, context)
        return resolved.backend, resolved.model, resolved.uri_params

    def _synchronize_request_with_target(
        self, request: ChatRequest, backend_type: str, effective_model: str
    ) -> ChatRequest:
        """Ensure the request payload reflects the resolved backend and model.

        Args:
            request: Original chat request
            backend_type: Resolved backend name
            effective_model: Resolved model name

        Returns:
            Request object updated with resolved backend/model information
        """
        from src.core.interfaces.backend_model_resolver_interface import ResolvedTarget

        resolved = ResolvedTarget(
            backend=backend_type,
            model=effective_model,
            uri_params={},  # URI params not needed for synchronization
        )
        return self._backend_model_resolver.synchronize_request_with_target(
            request, resolved
        )

    async def _check_complex_failover(
        self,
        request: ChatRequest,
        effective_model: str,
        backend_type: str,
        stream: bool,
        context: RequestContext | None,
    ) -> bool:
        """Check if complex failover should be executed for this request.

        Args:
            request: The chat completion request
            effective_model: The resolved model
            backend_type: The resolved backend
            stream: Whether streaming is enabled
            context: Optional request context

        Returns:
            True if complex failover was executed, False otherwise
        """
        request_failover_routes: dict[str, Any] | None = (
            request.extra_body.get("failover_routes") if request.extra_body else None
        )
        effective_failover_routes: dict[str, Any] = (
            request_failover_routes
            if request_failover_routes
            else self._failover_routes
        )

        return effective_model in effective_failover_routes

    async def _check_backend_availability(
        self, backend_type: str, effective_model: str, allow_failover: bool
    ) -> None:
        """Check if the backend is available (not disabled, not rate limited).

        Args:
            backend_type: The backend name
            effective_model: The model name
            allow_failover: Whether failover is allowed

        Raises:
            BackendError: If backend is permanently disabled
            RateLimitExceededError: If backend is rate limited
        """
        # Check if backend is permanently disabled
        disabled_info = self._backend_lifecycle_manager.get_disabled_backends().get(
            backend_type
        )
        if disabled_info and not (
            allow_failover
            and (
                effective_model in self._failover_routes
                or backend_type in self._failover_routes
            )
        ):
            raise BackendError(
                message=(
                    f"Backend {backend_type} is permanently disabled: "
                    f"{disabled_info.get('reason', 'authentication failed')}"
                ),
                backend_name=backend_type,
            )

        # Check resilience coordinator for instance/model availability
        if self._resilience:
            decision = self._resilience.check_availability(
                backend_type, effective_model
            )
            if not decision.should_proceed():
                cooldown_info = (
                    f" (retry after {decision.cooldown_remaining:.1f}s)"
                    if decision.cooldown_remaining
                    else ""
                )
                raise RateLimitExceededError(
                    message=f"{decision.reason}{cooldown_info}",
                    reset_at=(
                        time.time() + decision.cooldown_remaining
                        if decision.cooldown_remaining
                        else None
                    ),
                )

    async def _acquire_backend(
        self, backend_type: str, session_id: str | None
    ) -> LLMBackend:
        """Get or create a backend instance and verify it's healthy.

        Args:
            backend_type: The backend name
            session_id: Optional session ID for per-session backends

        Returns:
            The backend instance

        Raises:
            BackendError: If backend cannot be initialized or is unhealthy
            RateLimitExceededError: If backend is rate limited
        """
        # Initialize backend only after passing rate limiting checks
        try:
            backend = await self._backend_lifecycle_manager.get_or_create(
                backend_type, session_id=session_id
            )
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            raise BackendError(
                message=f"Failed to initialize backend {backend_type}",
                backend_name=backend_type,
                details={"error": str(e)},
            ) from e

        # Check if backend is rate limited by retry-after
        if hasattr(backend, "get_retry_after_remaining"):
            retry_after_remaining = backend.get_retry_after_remaining()
            if retry_after_remaining is not None:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Backend %s is rate limited, retry after %.1f seconds",
                        backend_type,
                        retry_after_remaining,
                    )
                raise RateLimitExceededError(
                    message=f"Backend {backend_type} is rate limited",
                    details={
                        "backend": backend_type,
                        "retry_after_seconds": retry_after_remaining,
                    },
                    reset_at=time.time() + retry_after_remaining,
                )

        # Check if backend is functional, with recovery attempt
        if (
            hasattr(backend, "is_backend_functional")
            and not backend.is_backend_functional()
        ):
            # Try to recover the backend before giving up
            recovered = False
            if hasattr(backend, "_validate_runtime_credentials"):
                try:
                    recovered = await backend._validate_runtime_credentials()
                    if recovered and logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Backend %s recovered after validation check",
                            backend_type,
                        )
                except Exception as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Backend %s recovery attempt failed: %s",
                            backend_type,
                            e,
                        )

            # Re-check functional status after recovery attempt
            if not recovered and not backend.is_backend_functional():
                # Get detailed validation errors if available
                validation_errors: list[str] = []
                if hasattr(backend, "get_validation_errors"):
                    validation_errors = backend.get_validation_errors()

                error_details: dict[str, Any] = {
                    "reason": "Backend reported as non-functional",
                }

                if validation_errors:
                    error_details["validation_errors"] = validation_errors
                    error_message = f"Backend {backend_type} is not functional: {'; '.join(validation_errors)}"
                else:
                    error_message = f"Backend {backend_type} is not functional"

                # Log the error for visibility
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Backend %s is not functional: %s",
                        backend_type,
                        error_message,
                    )

                raise BackendError(
                    message=error_message,
                    backend_name=backend_type,
                    details=error_details,
                )

        return backend

    async def _resolve_session(
        self, context: RequestContext | None, request: ChatRequest
    ) -> tuple[Any | None, str | None]:
        """Resolve session from context or request.

        Args:
            context: Optional request context
            request: The chat completion request

        Returns:
            Tuple of (session, session_id_for_backend)
        """
        session: Any | None = None
        session_id_for_backend: str | None = None

        # Resolve session from context when available
        if context and context.session_id:
            session_id_for_backend = context.session_id
            try:
                session = await self._session_service.get_session(context.session_id)
            except Exception:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to load session '%s' for backend call",
                        context.session_id,
                        exc_info=True,
                    )
                session = None

        # Try to get session from request extra_body if not found in context
        request_session_id = (
            request.extra_body.get("session_id") if request.extra_body else None
        )
        if (
            session is None
            and isinstance(request_session_id, str)
            and request_session_id
        ):
            if session_id_for_backend is None:
                session_id_for_backend = request_session_id
            try:
                session = await self._session_service.get_session(request_session_id)
            except Exception:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Could not load session {request_session_id} for backend from backend-only service"
                    )
                session = None

        return session, session_id_for_backend

    async def _prepare_backend_request(
        self,
        request: ChatRequest,
        backend_type: str,
        session: Any | None,
        uri_params: dict[str, Any],
    ) -> ChatRequest:
        """Apply reasoning config, backend config, and URI parameters to the request.

        Args:
            request: The original request
            backend_type: The backend name
            session: Optional session object
            uri_params: URI parameters to apply

        Returns:
            Transformed request ready for backend invocation
        """
        domain_request: ChatRequest = request

        # Apply session reasoning configuration if available
        if session is not None:
            try:
                domain_request = self._reasoning_config_applicator.apply(
                    domain_request, session
                )
            except Exception:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to apply reasoning config from session",
                        exc_info=True,
                    )

        # Apply backend configuration
        if self._backend_config_service:
            domain_request = self._backend_config_service.apply_backend_config(
                domain_request, backend_type, cast(AppConfig, self._config)
            )

        # Apply URI parameters with precedence resolution
        if uri_params:
            try:
                domain_request = self._uri_parameter_applicator.apply(
                    domain_request, uri_params, backend_type, session
                )
            except Exception:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to apply URI parameters",
                        exc_info=True,
                    )

        return domain_request

    async def _prepare_wire_capture_context(
        self, backend_type: str, session: Any | None
    ) -> Any:
        """Prepare identity and backend config for wire capture.

        Args:
            backend_type: The backend name
            session: Optional session object

        Returns:
            Identity object with session context
        """
        from src.core.config.app_config import BackendConfig

        app_config_typed: AppConfig = cast(AppConfig, self._config)

        # Fetch config from provider
        provider_backend_config = None
        if self._backend_config_service:
            config_or_app = self._backend_config_service.get_backend_config(
                backend_type
            )
            if isinstance(config_or_app, BackendConfig):
                provider_backend_config = config_or_app

        # Determine identity
        if provider_backend_config and getattr(
            provider_backend_config, "identity", None
        ):
            identity = provider_backend_config.identity
        else:
            backend_config_from_app = app_config_typed.backends.get(backend_type)
            identity = (
                backend_config_from_app.identity
                if backend_config_from_app and backend_config_from_app.identity
                else app_config_typed.identity
            )

        # Populate session turn count if session is available
        if session and hasattr(session, "history") and identity:
            identity = identity.model_copy(
                update={"session_turn_count": len(session.history)}
            )

        return identity

    async def _capture_wire_outbound(
        self,
        backend_type: str,
        effective_model: str,
        domain_request: ChatRequest,
        context: RequestContext | None,
    ) -> None:
        """Capture outbound wire payload (best-effort).

        Args:
            backend_type: The backend name
            effective_model: The model name
            domain_request: The request to capture
            context: Optional request context
        """
        try:
            if self._wire_capture and self._wire_capture.enabled():
                key_name = self._detect_key_name(backend_type)
                session_id = getattr(context, "session_id", None)
                await self._wire_capture.capture_outbound_request(
                    context=context,
                    session_id=session_id,
                    backend=backend_type,
                    model=effective_model,
                    key_name=key_name,
                    request_payload=domain_request,
                )
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Wire capture (request) failed for backend %s with model %s",
                    backend_type,
                    effective_model,
                    exc_info=True,
                )

    def _prepare_backend_kwargs(
        self,
        session_id_for_backend: str | None,
        session: Any | None,
        context: RequestContext | None,
        backend_type: str,
    ) -> dict[str, Any]:
        """Prepare kwargs for backend call.

        Args:
            session_id_for_backend: Optional session ID
            session: Optional session object
            context: Optional request context
            backend_type: The backend name

        Returns:
            Dictionary of kwargs for backend.chat_completions()
        """
        backend_call_kwargs: dict[str, Any] = {}

        if session_id_for_backend:
            backend_call_kwargs["session_id"] = session_id_for_backend

        if session is not None and hasattr(session, "state"):
            try:
                project_value = getattr(session.state, "project", None)
                if isinstance(project_value, str) and project_value:
                    backend_call_kwargs["project"] = project_value
            except Exception:
                pass
            try:
                project_dir_value = getattr(session.state, "project_dir", None)
                if isinstance(project_dir_value, str) and project_dir_value:
                    backend_call_kwargs["project_dir"] = project_dir_value
            except Exception:
                pass

        # Special handling for cline backend
        if context is not None and backend_type == "cline":
            try:
                incoming_headers = getattr(context, "headers", None)
                headers_dict: dict[str, Any] | None = None

                to_dict = getattr(incoming_headers, "to_dict", None)
                if callable(to_dict):
                    headers_dict = cast(dict[str, Any], to_dict())
                elif incoming_headers:
                    headers_dict = dict(incoming_headers)

                if headers_dict is not None:
                    backend_call_kwargs["incoming_headers"] = headers_dict
            except Exception:
                pass

        return backend_call_kwargs

    async def _calculate_and_record_usage(
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

    async def _wrap_response_for_usage(
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

    async def _execute_backend_call(
        self,
        backend: LLMBackend,
        backend_type: str,
        effective_model: str,
        domain_request: ChatRequest,
        request: ChatRequest,
        identity: Any,
        session: Any | None,
        session_id_for_backend: str | None,
        context: RequestContext | None,
        start_time: float,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute the backend call with wire capture and usage tracking.

        Args:
            backend: The backend instance
            backend_type: The backend name
            effective_model: The model name
            domain_request: The transformed request
            request: The original request
            identity: Identity context
            session: Optional session object
            session_id_for_backend: Optional session ID
            context: Optional request context
            start_time: Request start timestamp

        Returns:
            Response from the backend
        """
        # Wire-capture: capture outbound payload pre-call (best-effort)
        await self._capture_wire_outbound(
            backend_type=backend_type,
            effective_model=effective_model,
            domain_request=domain_request,
            context=context,
        )

        # Prepare backend call kwargs
        backend_call_kwargs = self._prepare_backend_kwargs(
            session_id_for_backend=session_id_for_backend,
            session=session,
            context=context,
            backend_type=backend_type,
        )

        # Calculate outbound tokens and record usage
        outbound_tokens, ctp_record_id, ptb_record_id = (
            await self._calculate_and_record_usage(
                domain_request=domain_request,
                request=request,
                backend_type=backend_type,
                effective_model=effective_model,
                session=session,
                session_id_for_backend=session_id_for_backend,
            )
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
        result = await self._wrap_response_for_usage(
            result=result,
            outbound_tokens=outbound_tokens,
            ctp_record_id=ctp_record_id,
            ptb_record_id=ptb_record_id,
            start_time=start_time,
        )

        return result

    async def _handle_streaming_response(
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
                key_name = self._detect_key_name(backend_type)

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

    async def _handle_non_streaming_response(
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

    async def _handle_auth_failure(
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

    async def _handle_backend_error(
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

                key_name = self._detect_key_name(backend_type)
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

    async def _apply_failure_recovery(
        self,
        error: Exception,
        model: str,
        backend_type: str,
        attempted_backends: list[str],
        start_time: float,
        is_streaming: bool,
        content_started: bool,
        request: ChatRequest,
        context: RequestContext | None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Apply failure handling strategy to decide retry/failover.

        Args:
            error: The error that occurred
            model: The model name
            backend_type: The backend name
            attempted_backends: List of already attempted backends
            start_time: Request start timestamp
            is_streaming: Whether streaming is enabled
            content_started: Whether content has started streaming
            request: The request
            context: Optional request context

        Returns:
            Response from retry or failover attempt

        Raises:
            The original error if recovery is not possible
        """
        # Track this backend as attempted
        if backend_type not in attempted_backends:
            attempted_backends.append(backend_type)

        # Check if we have a failure strategy configured
        if self._failure_strategy is None:
            logger.warning(
                "No failure handling strategy configured - errors will not "
                "be retried automatically. Consider configuring a failure strategy."
            )
            if isinstance(error, BackendError | RateLimitExceededError | LLMProxyError):
                raise error
            raise BackendError(
                message=f"Backend call failed: {error!s}",
                backend_name=backend_type,
            ) from error

        # Normalize the error for the strategy
        normalized_error = (
            error
            if isinstance(error, BackendError)
            else BackendError(
                message=str(error),
                backend_name=backend_type,
            )
        )

        # Consult the failure strategy
        failure_decision, wait_seconds, next_backend = (
            await self._apply_failure_strategy(
                error=normalized_error,
                model=model,
                backend_type=backend_type,
                attempted_backends=attempted_backends,
                start_time=start_time,
                is_streaming=is_streaming,
                content_started=content_started,
            )
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Failure strategy decision for %s/%s: %s, wait=%s, next=%s",
                backend_type,
                model,
                failure_decision,
                wait_seconds,
                next_backend,
            )

        if failure_decision == FailureDecision.WAIT_AND_RETRY:
            return await self._execute_retry(
                request=request,
                backend_type=backend_type,
                wait_seconds=wait_seconds,
                is_streaming=is_streaming,
                model=model,
                context=context,
                attempted_backends=attempted_backends,
            )

        if (
            failure_decision == FailureDecision.FAILOVER_IMMEDIATE
            and next_backend is not None
        ):
            return await self._execute_failover(
                request=request,
                next_backend=next_backend,
                is_streaming=is_streaming,
                backend_type=backend_type,
                model=model,
                context=context,
            )

        # SURFACE_ERROR or no next backend - raise the error
        if isinstance(error, BackendError | RateLimitExceededError | LLMProxyError):
            raise error
        raise BackendError(
            message=f"Backend call failed: {error!s}",
            backend_name=backend_type,
        ) from error

    async def _execute_retry(
        self,
        request: ChatRequest,
        backend_type: str,
        wait_seconds: float | None,
        is_streaming: bool,
        model: str,
        context: RequestContext | None,
        attempted_backends: list[str],
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute retry of the same backend after waiting.

        Args:
            request: The request
            backend_type: The backend to retry
            wait_seconds: How long to wait before retrying
            is_streaming: Whether streaming is enabled
            model: The model name
            context: Optional request context
            attempted_backends: List of attempted backends

        Returns:
            Response from retry attempt
        """
        if wait_seconds is not None and wait_seconds > 0:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Failure strategy: waiting %.1fs before retrying %s/%s",
                    wait_seconds,
                    backend_type,
                    model,
                )
            # Only sleep here for non-streaming requests
            if not (is_streaming or getattr(request, "stream", False)):
                await asyncio.sleep(wait_seconds)

        # Remove from attempted to allow retry
        if attempted_backends and attempted_backends[-1] == backend_type:
            attempted_backends.pop()

        # Create modified request to retry same backend
        retry_request = request.model_copy(
            update={
                "extra_body": {
                    **(request.extra_body or {}),
                    "backend_type": backend_type,
                }
            }
        )

        # For streaming, send keepalives during the wait
        if is_streaming or getattr(request, "stream", False):
            from src.core.services.streaming_keepalive import KeepAliveGenerator

            capture_session_id = None
            if context is not None:
                capture_session_id = getattr(context, "session_id", None)

            async def _wait_and_retry_stream() -> Any:
                # 1. Yield keepalives during the wait
                if wait_seconds and wait_seconds > 0:
                    # Use configured keepalive interval or default
                    ka_interval = 8.0
                    if hasattr(self._config, "failure_handling"):
                        ka_interval = getattr(
                            self._config.failure_handling,
                            "keepalive_interval",
                            8.0,
                        )

                    async for chunk in KeepAliveGenerator(
                        wait_seconds=wait_seconds,
                        interval_seconds=ka_interval,
                        include_status=True,
                        model=model,
                        session_id=capture_session_id,
                        stream_id=capture_session_id,
                    ):
                        yield chunk

                # 2. Execute retry
                try:
                    result = await self.call_completion(
                        retry_request,
                        stream=True,
                        allow_failover=True,
                        context=context,
                    )

                    # 3. Yield from the successful retry
                    if isinstance(result, StreamingResponseEnvelope):
                        async for chunk in result.content:  # type: ignore
                            yield chunk
                    else:
                        yield result.content
                except Exception as e:
                    logger.error(f"Retry failed during stream: {e}", exc_info=True)
                    from src.core.interfaces.response_processor_interface import (
                        ProcessedResponse,
                    )

                    error_details = {
                        "type": type(e).__name__,
                        "message": str(e),
                        "retryable": False,
                    }
                    yield ProcessedResponse(
                        content={
                            "choices": [
                                {
                                    "delta": {},
                                    "finish_reason": "error",
                                    "index": 0,
                                }
                            ],
                            "error": error_details,
                        },
                        metadata={
                            "finish_reason": "error",
                            "error": error_details,
                            "is_done": True,
                            "model": model,
                        },
                        usage=None,
                    )

            return StreamingResponseEnvelope(
                content=_wait_and_retry_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )

        # Non-streaming: just recurse after sleep (already slept above)
        return await self.call_completion(
            retry_request,
            stream=is_streaming,
            allow_failover=True,
            context=context,
        )

    async def _execute_failover(
        self,
        request: ChatRequest,
        next_backend: str,
        is_streaming: bool,
        backend_type: str,
        model: str,
        context: RequestContext | None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute failover to an alternative backend.

        Args:
            request: The request
            next_backend: The backend to failover to
            is_streaming: Whether streaming is enabled
            backend_type: The current backend
            model: The model name
            context: Optional request context

        Returns:
            Response from failover attempt
        """
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Failure strategy: failing over from %s to %s for model %s",
                backend_type,
                next_backend,
                model,
            )

        # Create request targeting the new backend
        failover_request = request.model_copy(
            update={
                "extra_body": {
                    **(request.extra_body or {}),
                    "backend_type": next_backend,
                }
            }
        )

        return await self.call_completion(
            failover_request,
            stream=is_streaming,
            allow_failover=True,
            context=context,
        )

    async def _execute_complex_failover(
        self,
        request: ChatRequest,
        effective_model: str,
        backend_type: str,
        stream: bool,
        context: RequestContext | None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute complex failover strategy for models with configured routes.

        Args:
            request: The request
            effective_model: The model name
            backend_type: The backend name
            stream: Whether streaming is enabled
            context: Optional request context

        Returns:
            Response from failover attempt
        """
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Using complex failover policy for model {effective_model}")

        try:
            from src.core.domain.configuration.backend_config import (
                BackendConfiguration,
            )

            request_failover_routes: dict[str, Any] | None = (
                request.extra_body.get("failover_routes")
                if request.extra_body
                else None
            )
            effective_failover_routes: dict[str, Any] = (
                request_failover_routes
                if request_failover_routes
                else self._failover_routes
            )

            _backend_config: BackendConfiguration = BackendConfiguration(
                backend_type=backend_type,
                model=effective_model,
                failover_routes_data=effective_failover_routes,
            )

            plan: list[tuple[str, str]] = self._failover_planner.get_failover_plan(
                effective_model, backend_type
            )

            return await self._attempt_failover_plan(
                request, plan, stream, backend_type, context
            )
        except BackendError:
            raise
        except (TypeError, ValueError, AttributeError, KeyError) as failover_error:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Failover processing failed: {failover_error!s}", exc_info=True
                )
            raise BackendError(
                message="all backends failed", backend_name=backend_type
            ) from failover_error

    async def _attempt_failover_plan(
        self,
        request: ChatRequest,
        plan: list[tuple[str, str]],
        stream: bool,
        backend_type: str,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Attempt failover using the provided plan.

        Args:
            request: The original request
            plan: List of (backend, model) tuples to attempt
            stream: Whether the request is a streaming request
            backend_type: The original backend type
            context: Optional request context

        Returns:
            Response from the first successful attempt

        Raises:
            BackendError: If all attempts fail
        """
        last_error: Exception | None = None
        if not plan:
            raise BackendError(message="all backends failed", backend_name=backend_type)

        for backend_attempt, model_attempt in plan:
            try:
                attempt_extra_body: dict[str, Any] = (
                    request.extra_body.copy() if request.extra_body else {}
                )
                attempt_extra_body["backend_type"] = backend_attempt

                attempt_request: ChatRequest = request.model_copy(
                    update={
                        "extra_body": attempt_extra_body,
                        "model": model_attempt,
                    }
                )

                return await self.call_completion(
                    attempt_request,
                    stream=stream,
                    allow_failover=False,
                    context=context,
                )
            except (BackendError, RateLimitExceededError) as attempt_error:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Failover attempt failed for {backend_attempt}:{model_attempt}: {attempt_error!s}",
                        exc_info=True,
                    )
                last_error = attempt_error
                continue
            except Exception as attempt_error:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        f"Unexpected error during failover attempt for {backend_attempt}:{model_attempt}: {attempt_error!s}",
                        exc_info=True,
                    )
                last_error = attempt_error
                continue

        if last_error:
            raise BackendError(
                message=f"All failover attempts failed. Last error: {last_error!s}",
                backend_name=backend_type,
            )
        else:
            raise BackendError(
                message="All failover attempts failed. No error details available.",
                backend_name=backend_type,
            )

    async def _apply_failure_strategy(
        self,
        error: BackendError,
        model: str,
        backend_type: str,
        attempted_backends: list[str],
        start_time: float,
        is_streaming: bool,
        content_started: bool,
    ) -> tuple[FailureDecision, float | None, str | None]:
        """Apply failure handling strategy to decide how to handle a backend failure.

        Args:
            error: The backend error that occurred
            model: Fully qualified model name
            backend_type: Name of the backend instance that failed
            attempted_backends: List of backend instances already tried
            start_time: Timestamp when the original request started
            is_streaming: Whether this is a streaming request
            content_started: Whether content has already been sent to client

        Returns:
            Tuple of (decision, wait_seconds, next_backend)
        """
        # For backward compatibility with tests that mock BackendService._apply_failure_strategy
        if self._parent_service is not None and hasattr(
            self._parent_service, "_apply_failure_strategy"
        ):
            parent_method = self._parent_service._apply_failure_strategy
            # Check if it's been mocked (has return_value attribute)
            if hasattr(parent_method, "return_value") or hasattr(
                parent_method, "side_effect"
            ):
                # It's a mock, use it
                return await parent_method(  # type: ignore[no-any-return]
                    error=error,
                    model=model,
                    backend_type=backend_type,
                    attempted_backends=attempted_backends,
                    start_time=start_time,
                    is_streaming=is_streaming,
                    content_started=content_started,
                )

        if self._failure_strategy is None:
            # No failure strategy configured, surface all errors
            return FailureDecision.SURFACE_ERROR, None, None

        elapsed_time = time.time() - start_time

        # Find available backend alternatives
        available_backends: list[str] | None = None
        if self._routing_service is not None:
            available_backends = self._routing_service.find_alternative_instances(
                model, [*attempted_backends, backend_type]
            )

        result = self._failure_strategy.decide(
            error=error,
            model=model,
            current_backend=backend_type,
            attempted_backends=attempted_backends,
            elapsed_time=elapsed_time,
            is_streaming=is_streaming,
            content_started=content_started,
            available_backends=available_backends,
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Failure strategy decision for %s/%s: %s (reason: %s)",
                backend_type,
                model,
                result.decision.value,
                result.reason,
            )

        return result.decision, result.wait_seconds, result.next_backend

    def _detect_key_name(self, backend_type: str) -> str | None:
        """Derive API key name (env var) for the backend when possible.

        Args:
            backend_type: The backend name

        Returns:
            The key name or backend_type if not found
        """
        try:
            app_config: AppConfig = cast(AppConfig, self._config)
            backend_cfg = app_config.backends.get(backend_type)
            api_key_value: str | None = None
            if backend_cfg and getattr(backend_cfg, "api_key", None):
                keys = backend_cfg.api_key
                api_key_value = keys[0] if keys else None
            if not api_key_value:
                return backend_type

            env_base = {
                "openrouter": "OPENROUTER_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "zai": "ZAI_API_KEY",
                "zenmux": "ZENMUX_API_KEY",
                "minimax": "MINIMAX_API_KEY",
            }.get(backend_type)
            if not env_base:
                return backend_type
            mapping = _collect_api_keys(env_base)
            for name, value in mapping.items():
                if value == api_key_value:
                    return name
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("_detect_key_name failed", exc_info=True)
        return backend_type
