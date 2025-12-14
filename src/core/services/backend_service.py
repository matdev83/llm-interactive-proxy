from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from typing import Any, cast
from uuid import uuid4

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
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.exception_normalizer_interface import IExceptionNormalizer
from src.core.interfaces.failover_interface import (
    IFailoverCoordinator,
    IFailoverStrategy,
)
from src.core.interfaces.failure_strategy_interface import (
    FailureDecision,
    IFailureHandlingStrategy,
)
from src.core.interfaces.model_alias_resolver_interface import IModelAliasResolver
from src.core.interfaces.planning_phase_manager_interface import IPlanningPhaseManager
from src.core.interfaces.rate_limiter_interface import IRateLimiter
from src.core.interfaces.reasoning_config_applicator_interface import (
    IReasoningConfigApplicator,
)
from src.core.interfaces.resilience_interface import (
    IResilienceCoordinator,
)
from src.core.interfaces.session_service_interface import ISessionService
from src.core.interfaces.stream_formatting_interface import IStreamFormattingService
from src.core.interfaces.uri_parameter_applicator_interface import (
    IURIParameterApplicator,
)
from src.core.interfaces.usage_tracking_interface import IUsageTrackingService
from src.core.interfaces.usage_tracking_wrapper_interface import IUsageTrackingWrapper
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_routing_service import BackendRoutingService
from src.core.services.failover_service import FailoverService

logger = logging.getLogger(__name__)


class BackendService(IBackendService):
    """Service for interacting with LLM backends.

    This service manages backend selection, rate limiting, and failover.
    """

    def __init__(
        self,
        factory: BackendFactory,
        rate_limiter: IRateLimiter,
        config: IConfig,
        session_service: ISessionService,  # Add session_service
        app_state: IApplicationState,
        backend_config_provider: IBackendConfigProvider | None = None,
        failover_routes: dict[str, dict[str, Any]] | None = None,
        failover_strategy: IFailoverStrategy | None = None,
        failover_coordinator: IFailoverCoordinator | None = None,
        wire_capture: IWireCapture | None = None,
        routing_service: BackendRoutingService | None = None,
        resilience_coordinator: IResilienceCoordinator | None = None,
        failure_handling_strategy: IFailureHandlingStrategy | None = None,
        usage_tracking_service: IUsageTrackingService | None = None,
        stream_formatting_service: IStreamFormattingService | None = None,
        usage_tracking_wrapper: IUsageTrackingWrapper | None = None,
        model_alias_resolver: IModelAliasResolver | None = None,
        exception_normalizer: IExceptionNormalizer | None = None,
        backend_lifecycle_manager: IBackendLifecycleManager | None = None,
        planning_phase_manager: IPlanningPhaseManager | None = None,
        reasoning_config_applicator: IReasoningConfigApplicator | None = None,
        uri_parameter_applicator: IURIParameterApplicator | None = None,
    ):
        """Initialize the backend service.

        Args:
            factory: The factory for creating backends
            rate_limiter: The rate limiter for API calls
            config: Application configuration
            session_service: The session service
            app_state: Application state service
            backend_configs: Configurations for backends
            failover_routes: Routes for backend failover
            routing_service: Service for instance routing and discovery
            resilience_coordinator: Coordinator for rate limiting and error recovery
            failure_handling_strategy: Strategy for handling backend failures with retry/failover
            usage_tracking_service: Service for tracking usage metrics
        """
        self._factory = factory
        self._rate_limiter = rate_limiter
        self._config = config
        self._session_service = session_service  # Store session_service
        self._app_state = app_state
        self._backend_config_provider: IBackendConfigProvider | None = (
            backend_config_provider
        )
        self._backend_configs: dict[str, Any] = {}
        self._failover_routes: dict[str, dict[str, Any]] = failover_routes or {}
        self._failover_strategy: IFailoverStrategy | None = failover_strategy
        self._routing_service = routing_service
        self._resilience: IResilienceCoordinator | None = resilience_coordinator
        self._failure_strategy: IFailureHandlingStrategy | None = (
            failure_handling_strategy
        )
        if self._failure_strategy is None:
            failure_handling_settings = getattr(config, "failure_handling", None)
            enabled_setting = (
                getattr(failure_handling_settings, "enabled", None)
                if failure_handling_settings is not None
                else None
            )
            if failure_handling_settings is not None and isinstance(
                enabled_setting, bool
            ):
                enabled = enabled_setting
            else:
                enabled = False

            if failure_handling_settings is not None and enabled:
                from src.core.interfaces.failure_strategy_interface import (
                    FailureHandlingConfig,
                )
                from src.core.services.failure_handling_strategy import (
                    DefaultFailureHandlingStrategy,
                )

                def _coerce_float(name: str, default: float) -> float:
                    value = getattr(failure_handling_settings, name, default)
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        return default

                def _coerce_int(name: str, default: int) -> int:
                    value = getattr(failure_handling_settings, name, default)
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        return default

                self._failure_strategy = DefaultFailureHandlingStrategy(
                    config=FailureHandlingConfig(
                        max_silent_wait=_coerce_float("max_silent_wait", 60.0),
                        total_timeout_budget=_coerce_float(
                            "total_timeout_budget", 90.0
                        ),
                        keepalive_interval=_coerce_float("keepalive_interval", 8.0),
                        max_failover_hops=_coerce_int("max_failover_hops", 5),
                        min_retry_wait=_coerce_float("min_retry_wait", 1.0),
                    ),
                    backend_discovery=self._routing_service,
                )
        self._usage_tracking_service = usage_tracking_service
        # Stream formatting service - create default if not provided
        if stream_formatting_service is None:
            from src.core.services.stream_formatting_service import (
                StreamFormattingService,
            )

            self._stream_formatting_service: IStreamFormattingService = (
                StreamFormattingService()
            )
        else:
            self._stream_formatting_service = stream_formatting_service
        # Usage tracking wrapper - create default if not provided
        if usage_tracking_wrapper is None:
            from src.core.services.usage_tracking_wrapper import UsageTrackingWrapper

            self._usage_tracking_wrapper: IUsageTrackingWrapper = UsageTrackingWrapper(
                usage_tracking_service=usage_tracking_service,
                stream_formatting_service=self._stream_formatting_service,
            )
        else:
            self._usage_tracking_wrapper = usage_tracking_wrapper
        # Model alias resolver - create default if not provided
        if model_alias_resolver is None:
            from src.core.services.model_alias_resolver import ModelAliasResolver

            self._model_alias_resolver: IModelAliasResolver = ModelAliasResolver(
                config=config
            )
        else:
            self._model_alias_resolver = model_alias_resolver

        # Exception normalizer - create default if not provided
        if exception_normalizer is None:
            from src.core.services.exception_normalizer import ExceptionNormalizer

            self._exception_normalizer: IExceptionNormalizer = ExceptionNormalizer()
        else:
            self._exception_normalizer = exception_normalizer

        # Resolve per-session limit early for lifecycle manager
        self._per_session_backend_limit = self._resolve_per_session_backend_limit(
            config
        )

        # Backend lifecycle manager - create default if not provided
        if backend_lifecycle_manager is None:
            from src.core.services.backend_lifecycle_manager import (
                BackendLifecycleManager,
            )

            self._backend_lifecycle_manager: IBackendLifecycleManager = (
                BackendLifecycleManager(
                    factory=factory,
                    config=config,
                    backend_config_provider=backend_config_provider,
                    per_session_limit=self._per_session_backend_limit,
                )
            )
        else:
            self._backend_lifecycle_manager = backend_lifecycle_manager

        # Planning phase manager - create default if not provided
        if planning_phase_manager is None:
            from src.core.services.planning_phase_manager import PlanningPhaseManager

            self._planning_phase_manager: IPlanningPhaseManager = PlanningPhaseManager(
                session_service=session_service
            )
        else:
            self._planning_phase_manager = planning_phase_manager

        # Reasoning config applicator - create default if not provided
        if reasoning_config_applicator is None:
            from src.core.services.reasoning_config_applicator import (
                ReasoningConfigApplicator,
            )

            self._reasoning_config_applicator: IReasoningConfigApplicator = (
                ReasoningConfigApplicator()
            )
        else:
            self._reasoning_config_applicator = reasoning_config_applicator

        # URI parameter applicator - create default if not provided
        if uri_parameter_applicator is None:
            from src.core.services.uri_parameter_applicator import (
                URIParameterApplicator,
            )

            self._uri_parameter_applicator: IURIParameterApplicator = (
                URIParameterApplicator(config=config)
            )
        else:
            self._uri_parameter_applicator = uri_parameter_applicator
        from src.core.config.app_config import AppConfig
        from src.core.services.failover_coordinator import FailoverCoordinator

        # Ensure config is properly typed for type checking
        _typed_config = cast(AppConfig, config)

        self._failover_service: FailoverService = FailoverService(
            failover_routes=self._failover_routes
        )
        if failover_coordinator is None:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "BackendService: No IFailoverCoordinator provided; using default FailoverCoordinator. "
                    "Prefer injecting an IFailoverCoordinator via DI to adhere to DIP."
                )
            self._failover_coordinator: IFailoverCoordinator = FailoverCoordinator(
                self._failover_service
            )
        else:
            self._failover_coordinator = failover_coordinator
        # Use injected backend config provider or create default
        if backend_config_provider is not None:
            self._backend_config_service = backend_config_provider
        else:
            # Fallback for backward compatibility - create with app_config
            from src.core.config.app_config import AppConfig
            from src.core.services.backend_config_provider import BackendConfigProvider

            if isinstance(config, AppConfig):
                self._backend_config_service = BackendConfigProvider(config)
            else:
                # Create a minimal AppConfig for backward compatibility
                self._backend_config_service = BackendConfigProvider(AppConfig())
        # Assign wire_capture if provided
        self._wire_capture: IWireCapture | None = wire_capture

    def _resolve_per_session_backend_limit(self, config: IConfig) -> int:
        """Determine the cache size for per-session backends."""
        default_limit = 32
        try:
            session_config = getattr(config, "session", None)
            candidate = getattr(
                session_config, "max_per_session_backends", default_limit
            )
            if isinstance(candidate, int) and candidate > 0:
                return candidate
        except Exception as exc:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Falling back to default per-session backend limit: %s",
                    exc,
                    exc_info=True,
                )
        return default_limit

    @staticmethod
    def _is_per_session_cache_key(cache_key: str, backend_type: str) -> bool:
        """Return True when the cache key maps to a session-scoped backend."""
        return cache_key != backend_type

    @staticmethod
    def _stream_as_sse_bytes(
        stream: AsyncIterator[Any],
    ) -> AsyncIterator[bytes]:
        """Adapt a stream of domain chunks into SSE-encoded bytes.

        Accepts an async iterator that may yield ProcessedResponse, dict, str, or bytes
        and produces an async iterator of bytes suitable for wire capture and direct
        transport to clients.

        Note: This is a static method for backward compatibility. It delegates to
        StreamFormattingService for the actual implementation.
        """
        from src.core.services.stream_formatting_service import StreamFormattingService

        service = StreamFormattingService()
        return service.stream_as_sse_bytes(stream)

    def _resolve_stream_session_id(
        self,
        session_id: str | None,
        context: RequestContext | None,
        request: ChatRequest,
    ) -> str:
        """Resolve a stable identifier for streaming capture and buffering."""
        if session_id:
            return str(session_id)

        request_session = getattr(request, "session_id", None)
        if request_session:
            return str(request_session)

        try:
            extra_body = getattr(request, "extra_body", None)
            if isinstance(extra_body, dict):
                extra_session = extra_body.get("session_id")
                if extra_session:
                    return str(extra_session)
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to read session_id from request.extra_body", exc_info=True
                )

        context_request_id = getattr(context, "request_id", None) if context else None
        if context_request_id:
            return str(context_request_id)

        return uuid4().hex

    def _get_failover_plan(
        self, model: str, backend_type: str
    ) -> list[tuple[str, str]]:
        """Return an ordered plan of (backend, model) attempts.

        Uses the extracted strategy when enabled and available, otherwise falls
        back to coordinator-provided attempts.

        When circuit breaker is enabled, filters out backends whose API endpoints
        are unhealthy.
        """
        use_strategy: bool = False
        try:
            use_strategy = self._app_state.get_use_failover_strategy()
        except (AttributeError, KeyError) as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Could not get failover strategy from app state: {e}",
                    exc_info=True,
                )
            use_strategy = False

        if use_strategy and self._failover_strategy is not None:
            try:
                plan = self._failover_strategy.get_failover_plan(model, backend_type)
                return self._filter_unhealthy_backends(plan)
            except (BackendError, RateLimitExceededError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Failover strategy failed: {e}", exc_info=True)
                # Fall back to coordinator attempts on error

        attempts = self._failover_coordinator.get_failover_attempts(model, backend_type)
        plan = [(a.backend, a.model) for a in attempts]
        return self._filter_unhealthy_backends(plan)

    def _filter_unhealthy_backends(
        self, plan: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        """Filter out backends with unhealthy API endpoints.

        Args:
            plan: List of (backend, model) tuples.

        Returns:
            Filtered list excluding unhealthy backends (if circuit breaker enabled).
        """
        # Check if circuit breaker is enabled
        # Use getattr for defensive programming - test configs may not have health_check
        health_check = getattr(self._config, "health_check", None)
        if health_check is None or not getattr(
            health_check, "circuit_breaker_enabled", True
        ):
            return plan

        filtered: list[tuple[str, str]] = []
        disabled_backends = self._backend_lifecycle_manager.get_disabled_backends()
        active_backends = self._backend_lifecycle_manager.get_active_backends()
        for backend_name, model_name in plan:
            # Check permanently disabled registry first
            if backend_name in disabled_backends:
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Skipping backend %s (permanently disabled: %s) in failover plan",
                        backend_name,
                        disabled_backends[backend_name].get("reason", "unknown"),
                    )
                continue

            backend = active_backends.get(backend_name)
            if backend is None:
                # Some backends are session-scoped and cached under keys like
                # "<backend>:<session_id>" or "<backend>:default". If we have an
                # active instance for the requested backend type, reuse it for
                # health filtering.
                backend = active_backends.get(f"{backend_name}:default")

            if backend is None:
                # Backend not yet created, include it (health unknown)
                filtered.append((backend_name, model_name))
                continue

            if backend.is_backend_functional():
                filtered.append((backend_name, model_name))
            else:
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Skipping backend %s (unhealthy endpoint) in failover plan",
                        backend_name,
                    )

        if not filtered and plan:
            # If all backends were filtered out, return original plan
            # to avoid complete failure when health checks are too strict
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "All backends filtered as unhealthy, falling back to original plan"
                )
            return plan

        return filtered

    async def call_completion(
        self,
        request: ChatRequest,
        stream: bool = False,
        allow_failover: bool = True,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Call the LLM backend for a completion"""
        # Resolve backend type, effective model, and URI parameters
        backend_type, effective_model, uri_params = (
            await self._resolve_backend_and_model(request)
        )

        # Ensure the request payload reflects the resolved backend and model.
        request = self._synchronize_request_with_target(
            request, backend_type, effective_model
        )

        request_failover_routes: dict[str, Any] | None = (
            request.extra_body.get("failover_routes") if request.extra_body else None
        )
        effective_failover_routes: dict[str, Any] = (
            request_failover_routes
            if request_failover_routes
            else self._failover_routes
        )
        disabled_info = self._backend_lifecycle_manager.get_disabled_backends().get(
            backend_type
        )

        # Handle complex failover if configured for this model
        if allow_failover and effective_model in effective_failover_routes:
            return await self._execute_complex_failover(
                request,
                effective_model,
                backend_type,
                effective_failover_routes,
                stream,
                context,
            )

        # If backend is permanently disabled and no failover plan applies, fail fast
        if disabled_info and not (
            allow_failover
            and (
                effective_model in effective_failover_routes
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

        # Rate limiting is now handled by the ResilienceCoordinator above
        # and the FailureHandlingStrategy for retry/failover decisions

        # Initialize failure strategy tracking
        start_time = time.time()
        attempted_backends: list[str] = []
        current_backend = backend_type
        content_started = False

        try:
            session: Any | None = None
            session_id_for_backend: str | None = None

            # Resolve session from context when available so session-scoped
            # backends (e.g., gemini-cli-acp) keep their state isolated.
            if context and context.session_id:
                session_id_for_backend = context.session_id
                try:
                    session = await self._session_service.get_session(
                        context.session_id
                    )
                except Exception:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to load session '%s' for backend call",
                            context.session_id,
                            exc_info=True,
                        )
                    session = None

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
                    session = await self._session_service.get_session(
                        request_session_id
                    )
                except Exception:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            f"Could not load session {request_session_id} for backend from backend-only service"
                        )
                    # If session cannot be loaded, proceed without it
                    session = None

            # Initialize backend only after passing rate limiting checks
            try:
                backend = await self._backend_lifecycle_manager.get_or_create(
                    backend_type, session_id=session_id_for_backend
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
                # This handles cases where quota was exhausted but time has passed
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

                    # Raise as usual. For streaming requests, this preserves OpenAI
                    # behavior: if the backend fails before the stream starts, return an
                    # HTTP error response (many clients can auto-retry); SSE error chunks
                    # are only appropriate once the response stream has begun.
                    raise BackendError(
                        message=error_message,
                        backend_name=backend_type,
                        details=error_details,
                    )

            domain_request: ChatRequest = request

            # Apply session reasoning configuration if available
            if session is not None:
                try:
                    domain_request = self._reasoning_config_applicator.apply(
                        domain_request, session
                    )
                except Exception:
                    # Log but continue if session access fails
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to apply reasoning config from session",
                            exc_info=True,
                        )

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

            try:
                app_config_typed: AppConfig = cast(AppConfig, self._config)

                # Fetch config from provider instead of relying on side effects in self._backend_configs
                from src.core.config.app_config import BackendConfig

                provider_backend_config = None
                if self._backend_config_service:
                    config_or_app = self._backend_config_service.get_backend_config(
                        backend_type
                    )
                    if isinstance(config_or_app, BackendConfig):
                        provider_backend_config = config_or_app

                # Fallback to cached config if available (legacy support)
                if provider_backend_config is None:
                    provider_backend_config = self._backend_configs.get(backend_type)

                if provider_backend_config and getattr(
                    provider_backend_config, "identity", None
                ):
                    identity = provider_backend_config.identity
                else:
                    backend_config_from_app = app_config_typed.backends.get(
                        backend_type
                    )
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
                # Wire-capture: capture outbound payload pre-call (best-effort)
                try:
                    if self._wire_capture and self._wire_capture.enabled():
                        key_name = self._detect_key_name(backend_type)
                        # Get session_id from context, not from request.extra_body
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

                # Calculate outbound tokens AFTER all transformations
                # This tracks what we're actually sending to the backend
                try:
                    from src.core.utils.usage_recalculation import (
                        calculate_outbound_tokens,
                    )

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
                    ctp_record_id = None
                    ptb_record_id = None
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

                            ctp_record_id = (
                                await self._usage_tracking_service.record_request(
                                    session_id=sid,
                                    backend_type=backend_type,
                                    model=effective_model,
                                    frontend_type="openai",
                                    leg=TrafficLeg.CLIENT_TO_PROXY,
                                    prompt_tokens=verbatim_tokens,
                                    proxy_user=proxy_user,
                                )
                            )

                            ptb_record_id = (
                                await self._usage_tracking_service.record_request(
                                    session_id=sid,
                                    backend_type=backend_type,
                                    model=effective_model,
                                    frontend_type="openai",
                                    leg=TrafficLeg.PROXY_TO_BACKEND,
                                    prompt_tokens=outbound_tokens,
                                    proxy_user=proxy_user,
                                )
                            )
                        except Exception as e:
                            logger.warning(f"Failed to record request usage: {e}")

                except Exception:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to calculate outbound tokens or record usage",
                            exc_info=True,
                        )
                    outbound_tokens = 0
                    ctp_record_id = None
                    ptb_record_id = None

                try:
                    result: ResponseEnvelope | StreamingResponseEnvelope = (
                        await backend.chat_completions(
                            request_data=domain_request,
                            processed_messages=request.messages,
                            effective_model=effective_model,
                            identity=identity,
                            **backend_call_kwargs,
                        )
                    )

                    # Store outbound tokens in result metadata for tracking
                    if hasattr(result, "metadata") and result.metadata is None:
                        result.metadata = {}
                    if hasattr(result, "metadata") and isinstance(
                        result.metadata, dict
                    ):
                        result.metadata["outbound_tokens"] = outbound_tokens

                    # Wrap result content for usage tracking
                    if (
                        isinstance(result, StreamingResponseEnvelope)
                        and self._usage_tracking_service
                        and (ctp_record_id or ptb_record_id)
                    ):
                        if result.content is not None:
                            result.content = (
                                self._usage_tracking_wrapper.wrap_stream_for_usage(
                                    result.content,
                                    ctp_record_id,
                                    ptb_record_id,
                                    start_time,
                                )
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
                                if not isinstance(usage, dict) and hasattr(
                                    usage, "model_dump"
                                ):
                                    usage = usage.model_dump()

                                completion_tokens = usage.get("completion_tokens", 0)
                                duration_ms = (time.time() - start_time) * 1000

                                if ptb_record_id:
                                    await self._usage_tracking_service.record_response(
                                        record_id=ptb_record_id,
                                        completion_tokens=completion_tokens,
                                        backend_reported_usage=usage,
                                        http_status_code=getattr(
                                            result, "status_code", 200
                                        ),
                                        total_duration_ms=duration_ms,
                                    )

                                if ctp_record_id:
                                    await self._usage_tracking_service.record_response(
                                        record_id=ctp_record_id,
                                        completion_tokens=completion_tokens,
                                        backend_reported_usage=usage,
                                        http_status_code=getattr(
                                            result, "status_code", 200
                                        ),
                                        total_duration_ms=duration_ms,
                                    )
                        except Exception as e:
                            logger.error(
                                f"Failed to record response usage: {e}", exc_info=True
                            )

                except AttributeError:
                    # Result doesn't support metadata, skip
                    pass
                except AuthenticationError as exc:
                    if backend.has_static_credentials:
                        # Permanent auth failure for static backends (env vars)
                        if logger.isEnabledFor(logging.ERROR):
                            logger.error(
                                "Authentication failed for static backend %s: %s",
                                backend_type,
                                exc,
                            )
                        backend.mark_auth_invalid(str(exc))
                        self._factory.unregister_backend(backend_type)
                        self._backend_lifecycle_manager.discard(
                            backend_type, session_id_for_backend, reason=str(exc)
                        )
                    # For non-static (recoverable) backends, just raise.
                    # This allows is_backend_functional() to fail on next call,
                    # triggering _validate_runtime_credentials() logic.
                    raise

                except HTTPException as exc:
                    # Handle raw HTTPException (e.g. from FastAPI/Starlette)
                    if (
                        getattr(exc, "status_code", None) == 401
                        and backend.has_static_credentials
                    ):
                        if logger.isEnabledFor(logging.ERROR):
                            logger.error(
                                "Authentication failed for static backend %s: %s",
                                backend_type,
                                exc,
                            )
                        backend.mark_auth_invalid(
                            str(getattr(exc, "detail", "Unauthorized"))
                        )
                        self._factory.unregister_backend(backend_type)
                        self._backend_lifecycle_manager.discard(
                            backend_type,
                            session_id_for_backend,
                            reason=str(getattr(exc, "detail", "Unauthorized")),
                        )
                    # Re-raise for recoverable backends or non-401 errors
                    raise

                except BackendError as be:
                    # Handle 401 wrapped in BackendError
                    if getattr(be, "status_code", None) == 401:
                        if backend.has_static_credentials:
                            if logger.isEnabledFor(logging.ERROR):
                                logger.error(
                                    "Authentication failed for static backend %s: %s",
                                    backend_type,
                                    be,
                                )
                            backend.mark_auth_invalid(getattr(be, "message", str(be)))
                            self._factory.unregister_backend(backend_type)
                            self._backend_lifecycle_manager.discard(
                                backend_type,
                                session_id_for_backend,
                                reason=getattr(be, "message", str(be)),
                            )
                        # Re-raise for recoverable backends
                        raise

                    # All backend errors (including 429) are now handled by the
                    # failure handling strategy at the outer loop level
                    raise
                # Get session_id from context for stream correlation
                session_id = getattr(context, "session_id", None)
                session_id = self._resolve_stream_session_id(
                    session_id, context, domain_request
                )
                if context is not None and not getattr(context, "session_id", None):
                    with contextlib.suppress(Exception):
                        context.session_id = session_id
                # StreamingResponseEnvelope is imported at module level

                # Wire-capture: capture inbound
                try:
                    if self._wire_capture and self._wire_capture.enabled():
                        key_name = self._detect_key_name(backend_type)

                        if isinstance(result, StreamingResponseEnvelope):
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
                                byte_stream = (
                                    self._stream_formatting_service.stream_as_sse_bytes(
                                        result.content
                                    )
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
                            # IMPORTANT: Include session_id in metadata for stream correlation
                            # This ensures tool call buffering works correctly across chunks
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
                                    from src.core.interfaces.response_processor_interface import (
                                        ProcessedResponse,
                                    )

                                    await self._planning_phase_manager.update_counters(
                                        session_id,
                                        ProcessedResponse(content="", metadata={}),
                                    )

                            # Record success for streaming response
                            if self._resilience:
                                self._resilience.record_success(
                                    backend_type, effective_model
                                )

                            return StreamingResponseEnvelope(
                                content=_to_processed_with_capture(),
                                media_type=result.media_type,
                                headers=result.headers,
                                metadata=result.metadata,
                            )
                        else:
                            await self._wire_capture.capture_inbound_response(
                                context=context,
                                session_id=session_id,
                                backend=backend_type,
                                model=effective_model,
                                key_name=key_name,
                                response_content=result.content,
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

                # Record success in resilience coordinator
                if self._resilience:
                    self._resilience.record_success(backend_type, effective_model)

                if session_id_for_backend and self._planning_phase_manager:
                    await self._planning_phase_manager.update_counters(
                        session_id_for_backend, result
                    )

                return result
            except (
                Exception
            ) as call_exc:  # Catch all exceptions for comprehensive logging
                # DEBUG: Log that we caught an exception in the failure strategy handler
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "BackendService caught exception from %s: %s (type=%s, status=%s)",
                        current_backend,
                        call_exc,
                        type(call_exc).__name__,
                        getattr(call_exc, "status_code", None),
                    )

                call_exc = self._exception_normalizer.normalize(call_exc, backend_type)

                capture_session_id: str | None = None
                if context is not None:
                    capture_session_id = getattr(context, "session_id", None)
                if not capture_session_id:
                    capture_session_id = getattr(request, "session_id", None)

                # Best-effort wire-capture of error payloads so debugging captures
                # remain useful even when the backend call fails before streaming begins.
                try:
                    if self._wire_capture and self._wire_capture.enabled():
                        error_payload: dict[str, Any]
                        if isinstance(call_exc, LLMProxyError):
                            error_payload = call_exc.to_dict()
                            with contextlib.suppress(Exception):
                                if (
                                    isinstance(error_payload.get("error"), dict)
                                    and "status_code" not in error_payload["error"]
                                ):
                                    error_payload["error"]["status_code"] = getattr(
                                        call_exc, "status_code", None
                                    )
                        else:
                            error_payload = {
                                "error": {
                                    "message": str(call_exc),
                                    "type": type(call_exc).__name__,
                                }
                            }

                        key_name = self._detect_key_name(current_backend)
                        await self._wire_capture.capture_inbound_response(
                            context=context,
                            session_id=capture_session_id,
                            backend=current_backend,
                            model=effective_model,
                            key_name=key_name,
                            response_content=error_payload,
                        )
                except Exception:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Wire capture (error response) failed for backend %s with model %s",
                            current_backend,
                            effective_model,
                            exc_info=True,
                        )

                # Store retry-after in backend instance if this is a rate limit error
                if isinstance(call_exc, RateLimitExceededError) and hasattr(
                    backend, "set_retry_after"
                ):
                    reset_at = getattr(call_exc, "reset_at", None)
                    if reset_at is not None:
                        retry_after_seconds = reset_at - time.time()
                        if retry_after_seconds > 0:
                            backend.set_retry_after(retry_after_seconds)
                            if logger.isEnabledFor(logging.INFO):
                                logger.info(
                                    "Backend %s rate limited, cached retry-after for %.1f seconds",
                                    current_backend,
                                    retry_after_seconds,
                                )

                # If the exception is already a BackendError or RateLimitExceededError,
                # treat it specially; otherwise wrap or re-raise depending on allow_failover.
                if isinstance(call_exc, BackendError | RateLimitExceededError):
                    if not allow_failover:
                        # For streaming requests, preserve HTTP error semantics when
                        # the backend fails before the stream starts.
                        raise call_exc
                    last_error = call_exc
                else:
                    if not allow_failover:
                        # Immediate wrapping when failover is disabled
                        wrapped_error = BackendError(
                            message=f"Backend call failed: {call_exc!s}",
                            backend_name=current_backend,
                        )
                        raise wrapped_error from call_exc  # Chain the exception
                    last_error = call_exc  # type: ignore[assignment]

                # Use the failure handling strategy to decide next action
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failure strategy check: allow_failover=%s, _failure_strategy=%s",
                        allow_failover,
                        self._failure_strategy is not None,
                    )

                if not allow_failover:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug("Skipping failure strategy: allow_failover=False")
                elif self._failure_strategy is None:
                    logger.warning(
                        "No failure handling strategy configured - 429 errors will not "
                        "be retried automatically. Consider configuring a failure strategy."
                    )

                if allow_failover and self._failure_strategy is not None:
                    # Normalize the error for the strategy
                    normalized_error = (
                        last_error
                        if isinstance(last_error, BackendError)
                        else BackendError(
                            message=str(last_error),
                            backend_name=current_backend,
                        )
                    )

                    # Track this backend as attempted
                    if current_backend not in attempted_backends:
                        attempted_backends.append(current_backend)

                    # Consult the failure strategy
                    failure_decision, wait_seconds, next_backend = (
                        await self._apply_failure_strategy(
                            error=normalized_error,
                            model=effective_model,
                            backend_type=current_backend,
                            attempted_backends=attempted_backends,
                            start_time=start_time,
                            is_streaming=stream,
                            content_started=content_started,
                        )
                    )

                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failure strategy decision for %s/%s: %s, wait=%s, next=%s",
                            current_backend,
                            effective_model,
                            failure_decision,
                            wait_seconds,
                            next_backend,
                        )

                    if failure_decision == FailureDecision.WAIT_AND_RETRY:
                        if wait_seconds is not None and wait_seconds > 0:
                            if logger.isEnabledFor(logging.INFO):
                                logger.info(
                                    "Failure strategy: waiting %.1fs before retrying %s/%s",
                                    wait_seconds,
                                    current_backend,
                                    effective_model,
                                )
                            # Only sleep here for non-streaming requests.
                            # Streaming requests handle waiting via KeepAliveGenerator below.
                            if not (stream or getattr(request, "stream", False)):
                                await asyncio.sleep(wait_seconds)

                        # Remove from attempted to allow retry
                        if (
                            attempted_backends
                            and attempted_backends[-1] == current_backend
                        ):
                            attempted_backends.pop()

                        # Create modified request to retry same backend
                        retry_request = request.model_copy(
                            update={
                                "extra_body": {
                                    **(request.extra_body or {}),
                                    "backend_type": current_backend,
                                }
                            }
                        )

                        # For streaming, we can start sending keepalives immediately
                        # if the wait is significant, to prevent client timeouts
                        if stream or getattr(request, "stream", False):
                            from src.core.services.streaming_keepalive import (
                                KeepAliveGenerator,
                            )

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
                                        model=effective_model,
                                        session_id=capture_session_id,
                                        stream_id=capture_session_id,
                                    ):
                                        # Yield keepalive chunks to keep the client connection open
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
                                        # Should not happen for stream=True, but handle just in case
                                        yield result.content
                                except Exception as e:
                                    # If retry fails and can't be handled (e.g. fatal error),
                                    # we need to yield an error chunk since we already sent headers
                                    logger.error(
                                        f"Retry failed during stream: {e}",
                                        exc_info=True,
                                    )
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
                                            "model": effective_model,
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
                            stream=stream,
                            allow_failover=True,
                            context=context,
                        )

                    if (
                        failure_decision == FailureDecision.FAILOVER_IMMEDIATE
                        and next_backend is not None
                    ):
                        if logger.isEnabledFor(logging.INFO):
                            logger.info(
                                "Failure strategy: failing over from %s to %s for model %s",
                                current_backend,
                                next_backend,
                                effective_model,
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
                            stream=stream,
                            allow_failover=True,
                            context=context,
                        )

                    # SURFACE_ERROR or no next backend - fall through to raise

                # If we get here, re-raise the original error if it's already a domain error,
                # otherwise wrap it in BackendError
                if isinstance(
                    last_error, BackendError | RateLimitExceededError | LLMProxyError
                ):
                    raise last_error
                raise BackendError(
                    message=f"Backend call failed: {last_error!s}",
                    backend_name=current_backend,
                ) from last_error

        except (BackendError, RateLimitExceededError, LLMProxyError) as exc:
            # Record failure in resilience coordinator (handles cooldown/backoff)
            if self._resilience:
                self._resilience.record_failure(backend_type, effective_model, exc)
            # Propagate expected exceptions as-is
            raise
        except Exception as e:
            # Catch any other unexpected exceptions and wrap them
            raise BackendError(
                message=f"An unexpected error occurred during backend call to {backend_type}: {e!s}",
                backend_name=backend_type,
            ) from e

    async def validate_backend_and_model(
        self, backend: str, model: str
    ) -> tuple[bool, str | None]:
        """Validate that a backend and model combination is valid"""
        try:
            backend_instance: LLMBackend = (
                await self._backend_lifecycle_manager.get_or_create(backend)
            )

            available_models: list[str] = backend_instance.get_available_models()
            if model in available_models:
                return True, None

            return False, f"Model {model} not available on backend {backend}"
        except (BackendError, TypeError, ValueError, AttributeError) as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Backend validation failed for {backend}: {e!s}", exc_info=True
                )
            return False, f"Backend validation failed: {e!s}"

    # NOTE: Legacy rate limit backoff methods (_enforce_rate_limit_backoff,
    # _register_rate_limit_backoff) have been removed. Rate limiting is now
    # handled by the ResilienceCoordinator via the resilience layer.

    def get_backend(self, backend_type: str) -> LLMBackend:
        """Get a backend instance synchronously (for testing purposes)."""
        active_backends = self._backend_lifecycle_manager.get_active_backends()
        if backend_type in active_backends:
            return active_backends[backend_type]

        # For testing, create a simple backend instance
        from src.core.config.app_config import AppConfig

        app_config = cast(AppConfig, self._config)

        # Create backend using factory
        # Note: This creates a detached backend not managed by lifecycle manager
        return self._factory.create_backend(backend_type, app_config)

    async def chat_completions(
        self,
        request: ChatRequest,
        *,
        stream: bool = False,
        allow_failover: bool = True,
        context: RequestContext | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:  # type: ignore[override]
        """Handle chat completions with the LLM."""

        return await self.call_completion(
            request,
            stream=stream,
            allow_failover=allow_failover,
            context=context,
        )

    async def _resolve_backend_and_model(
        self, request: ChatRequest
    ) -> tuple[str, str, dict[str, Any]]:
        """Resolve backend type, effective model, and URI parameters from request and session"""
        session_id = (
            request.extra_body.get("session_id") if request.extra_body else None
        )
        session = (
            await self._session_service.get_session(session_id) if session_id else None
        )

        from src.core.config.app_config import AppConfig

        app_config: AppConfig = cast(AppConfig, self._config)
        default_backend: str = (
            app_config.backends.default_backend
            if hasattr(app_config, "backends")
            else "openai"
        )

        await self._planning_phase_manager.apply_if_needed(session, default_backend)

        backend_type: str | None = None
        excluded_backends = set(
            self._backend_lifecycle_manager.get_disabled_backends().keys()
        )
        if session and session.state and session.state.backend_config:
            from src.core.domain.configuration.backend_config import (
                BackendConfiguration,
            )

            backend_type = cast(
                BackendConfiguration, session.state.backend_config
            ).backend_type

        if not backend_type:
            backend_type = (
                request.extra_body.get("backend_type") if request.extra_body else None
            )

        effective_model: str = request.model

        # Apply model aliases BEFORE parsing backend from model name
        effective_model = self._model_alias_resolver.resolve(effective_model)

        # Parse model string with URI parameters
        uri_params: dict[str, Any] = {}
        if not backend_type:
            from src.core.domain.model_utils import parse_model_with_params

            # Pass empty string as default to detect if backend was specified
            parsed_backend, parsed_model, uri_params = parse_model_with_params(
                effective_model, ""
            )

            if not parsed_backend and self._routing_service:
                # Try discovery
                discovered = self._routing_service.resolve_backend_instance(
                    None, parsed_model, excluded_backends
                )
                if discovered:
                    parsed_backend = discovered

            # Fallback to default backend if discovery failed or not used
            backend_type = parsed_backend or default_backend
            effective_model = parsed_model

            # If we have a backend type (either parsed or default), try to route it (Variant 2)
            if self._routing_service:
                resolved = self._routing_service.resolve_backend_instance(
                    backend_type, effective_model, excluded_backends
                )
                if resolved:
                    if logger.isEnabledFor(logging.DEBUG) and resolved != backend_type:
                        logger.debug(
                            f"RoutingService resolved '{backend_type}' -> '{resolved}'"
                        )
                    backend_type = resolved

        else:
            # Backend type is already set (from session or extra_body)
            # Still need to parse URI parameters from the model string
            from src.core.domain.model_utils import parse_model_with_params

            # Parse with empty default backend since we already have backend_type
            _, parsed_model, uri_params = parse_model_with_params(effective_model, "")
            effective_model = parsed_model

            # Try to route the explicitly set backend (Variant 2)
            if self._routing_service:
                resolved = self._routing_service.resolve_backend_instance(
                    backend_type, effective_model, excluded_backends
                )
                if resolved:
                    if logger.isEnabledFor(logging.DEBUG) and resolved != backend_type:
                        logger.debug(
                            f"RoutingService resolved '{backend_type}' -> '{resolved}'"
                        )
                    backend_type = resolved

        # Apply static_route override if configured
        app_config = cast(AppConfig, self._config)
        if (
            hasattr(app_config, "backends")
            and hasattr(app_config.backends, "static_route")
            and app_config.backends.static_route
        ):
            static_route = app_config.backends.static_route
            # Parse backend:model format (check it's a string first)
            if isinstance(static_route, str) and ":" in static_route:
                forced_backend, forced_model = static_route.split(":", 1)
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        f"Applying static_route override: {backend_type}:{effective_model} -> {forced_backend}:{forced_model}"
                    )
                backend_type = forced_backend
                effective_model = forced_model
            else:
                # If no colon, treat as model only
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        f"Applying static_route model override: {effective_model} -> {static_route}"
                    )
                effective_model = static_route

        return backend_type, effective_model, uri_params

    def _synchronize_request_with_target(
        self, request: ChatRequest, backend_type: str, effective_model: str
    ) -> ChatRequest:
        """
        Ensure the request (and nested extra_body) reflect the backend/model chosen.

        Args:
            request: Original chat request from the client.
            backend_type: Resolved backend name.
            effective_model: Resolved model name.

        Returns:
            A request object updated with the resolved backend/model information.
        """
        updates: dict[str, Any] = {}

        # Preserve the original model format if it contains a backend prefix that matches
        # the resolved backend. This allows connectors to see the original client request.
        # However, if the backend was overridden (e.g., via static_route), update the model.
        should_update_model = False
        if request.model != effective_model:
            if ":" in request.model:
                # Model has backend prefix - check if it matches the resolved backend
                request_backend, _ = request.model.split(":", 1)
                if request_backend != backend_type:
                    # Backend was overridden, update the model
                    should_update_model = True
                # else: Backend matches, preserve original format
            else:
                # No backend prefix, update to effective model
                should_update_model = True

        if should_update_model:
            updates["model"] = effective_model

        extra_body = getattr(request, "extra_body", None)
        if isinstance(extra_body, dict):
            updated_extra_body = dict(extra_body)
            extra_changed = False

            if updated_extra_body.get("model") != effective_model:
                updated_extra_body["model"] = effective_model
                extra_changed = True

            if backend_type:
                if updated_extra_body.get("backend_type") != backend_type:
                    updated_extra_body["backend_type"] = backend_type
                    extra_changed = True
            elif "backend_type" in updated_extra_body:
                # Remove stale backend_type when backend resolution is empty.
                updated_extra_body.pop("backend_type")
                extra_changed = True

            if extra_changed:
                updates["extra_body"] = updated_extra_body

        if not updates:
            return request

        return request.model_copy(update=updates)

    def _detect_key_name(self, backend_type: str) -> str | None:
        """Derive API key name (env var) for the backend when possible.

        Falls back to the backend type when a specific name is not found.
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

    async def _execute_complex_failover(
        self,
        request: ChatRequest,
        effective_model: str,
        backend_type: str,
        effective_failover_routes: dict[str, Any],
        stream: bool,
        context: RequestContext | None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute complex failover strategy for models with configured routes"""
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Using complex failover policy for model {effective_model}")
        try:
            from src.core.domain.configuration.backend_config import (
                BackendConfiguration,
            )

            _backend_config: BackendConfiguration = BackendConfiguration(
                backend_type=backend_type,
                model=effective_model,
                failover_routes_data=effective_failover_routes,
            )

            plan: list[tuple[str, str]] = self._get_failover_plan(
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

    def get_active_backends(self) -> dict[str, LLMBackend]:
        """Get all active backend instances.

        Returns:
             A dictionary mapping backend instance names to LLMBackend objects.
        """
        return self._backend_lifecycle_manager.get_active_backends()

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
            error: The backend error that occurred.
            model: Fully qualified model name.
            backend_type: Name of the backend instance that failed.
            attempted_backends: List of backend instances already tried.
            start_time: Timestamp when the original request started.
            is_streaming: Whether this is a streaming request.
            content_started: Whether content has already been sent to client.

        Returns:
            Tuple of (decision, wait_seconds, next_backend).
        """
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

    # NOTE: Legacy _handle_backend_call_failover and _execute_with_failure_handling
    # methods have been removed. Failure handling is now integrated directly into
    # call_completion() using the IFailureHandlingStrategy.
    # Failure handling is now managed by the IFailureHandlingStrategy,
    # which is integrated directly into call_completion().

    # =========================================================================
    # Delegating wrappers for backward compatibility
    # These methods delegate to extracted services but preserve the original
    # method signatures for tests and debugging scripts.
    # =========================================================================

    def _wrap_stream_for_usage(
        self,
        stream: AsyncIterator[Any],
        ctp_record_id: str | None,
        ptb_record_id: str | None,
        start_time: float,
    ) -> AsyncIterator[Any]:
        """Wrap stream to track usage metrics.

        Delegating wrapper for backward compatibility.
        """
        return self._usage_tracking_wrapper.wrap_stream_for_usage(
            stream, ctp_record_id, ptb_record_id, start_time
        )

    def _apply_model_aliases(self, model: str) -> str:
        """Apply configured model aliases and return resolved model name.

        Delegating wrapper for backward compatibility.
        """
        return self._model_alias_resolver.resolve(model)

    def _apply_reasoning_config(
        self, request: ChatRequest, session: Any
    ) -> ChatRequest:
        """Apply reasoning configuration from session to request.

        Delegating wrapper for backward compatibility.
        """
        return self._reasoning_config_applicator.apply(request, session)

    def _apply_uri_parameters(
        self,
        request: ChatRequest,
        uri_params: dict[str, Any],
        backend_type: str,
        session: Any | None = None,
    ) -> ChatRequest:
        """Apply URI parameters to request with precedence resolution.

        Delegating wrapper for backward compatibility.
        """
        return self._uri_parameter_applicator.apply(
            request, uri_params, backend_type, session
        )

    def _is_valid_completion_token(self, chunk: Any) -> bool:
        """Check if chunk contains valid completion content.

        Delegating wrapper for backward compatibility.
        """
        return self._stream_formatting_service.is_valid_completion_token(chunk)

    def _normalize_provider_exception(
        self, exc: Exception, backend_type: str
    ) -> Exception:
        """Translate provider exception to domain error.

        Delegating wrapper for backward compatibility.
        """
        return self._exception_normalizer.normalize(exc, backend_type)

    async def _get_or_create_backend(
        self, backend_type: str, session_id: str | None = None
    ) -> LLMBackend:
        """Get existing backend or create new one.

        Delegating wrapper for backward compatibility.
        """
        return await self._backend_lifecycle_manager.get_or_create(
            backend_type, session_id
        )
