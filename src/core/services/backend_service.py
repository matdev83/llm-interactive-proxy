from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any, cast

from pydantic.types import JsonValue

from src.connectors.base import LLMBackend
from src.core.common.exceptions import (
    BackendError,
    RateLimitExceededError,
)
from src.core.config.app_config import AppConfig
from src.core.config.config_loader import _collect_api_keys
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_completion_flow_interface import (
    IBackendCompletionFlow,
)
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.backend_model_resolver_interface import (
    IBackendModelResolver,
)
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.exception_normalizer_interface import IExceptionNormalizer
from src.core.interfaces.failover_interface import (
    IFailoverCoordinator,
    IFailoverStrategy,
)
from src.core.interfaces.failover_planner_interface import IFailoverPlanner
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
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)
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
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_routing_service import BackendRoutingService
from src.core.services.failover_service import FailoverService
from src.core.services.stream_formatting_service import StreamFormattingService

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _legacy_stream_formatting_service() -> StreamFormattingService:
    return StreamFormattingService()


class BackendService(IBackendService):
    """Service for interacting with LLM backends.

    This service manages backend selection, rate limiting, and failover.
    """

    def __init__(
        self,
        factory: BackendFactory,
        rate_limiter: IRateLimiter,
        config: IConfig,
        session_service: ISessionService,
        app_state: IApplicationState,
        backend_config_provider: IBackendConfigProvider,
        # Required collaborators (Phase 1-3 extractions) - no fallbacks
        stream_formatting_service: IStreamFormattingService,
        usage_tracking_wrapper: IUsageTrackingWrapper,
        model_alias_resolver: IModelAliasResolver,
        exception_normalizer: IExceptionNormalizer,
        backend_lifecycle_manager: IBackendLifecycleManager,
        planning_phase_manager: IPlanningPhaseManager,
        reasoning_config_applicator: IReasoningConfigApplicator,
        uri_parameter_applicator: IURIParameterApplicator,
        stream_session_id_resolver: IStreamSessionIdResolver,
        backend_model_resolver: IBackendModelResolver,
        failover_planner: IFailoverPlanner,
        backend_completion_flow: IBackendCompletionFlow,
        # Optional infrastructure services
        failover_routes: dict[str, dict[str, Any]] | None = None,
        failover_strategy: IFailoverStrategy | None = None,
        failover_coordinator: IFailoverCoordinator | None = None,
        wire_capture: IWireCapture | None = None,
        routing_service: BackendRoutingService | None = None,
        resilience_coordinator: IResilienceCoordinator | None = None,
        failure_handling_strategy: IFailureHandlingStrategy | None = None,
        usage_tracking_service: IUsageTrackingService | None = None,
        cancellation_coordinator: ISessionCancellationCoordinator | None = None,
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
        self._usage_tracking_service = usage_tracking_service
        self._stream_formatting_service = stream_formatting_service
        self._usage_tracking_wrapper = usage_tracking_wrapper
        self._model_alias_resolver = model_alias_resolver
        self._exception_normalizer = exception_normalizer

        # Resolve per-session limit early for lifecycle manager (used by validation)
        self._per_session_backend_limit = self._resolve_per_session_backend_limit(
            config
        )

        self._backend_lifecycle_manager = backend_lifecycle_manager
        self._planning_phase_manager = planning_phase_manager
        self._reasoning_config_applicator = reasoning_config_applicator
        self._uri_parameter_applicator = uri_parameter_applicator
        self._stream_session_id_resolver = stream_session_id_resolver
        self._backend_model_resolver = backend_model_resolver

        # Store legacy failover service for backward compatibility
        self._failover_service: FailoverService = FailoverService(
            failover_routes=self._failover_routes
        )

        self._failover_coordinator = failover_coordinator
        self._failover_planner = failover_planner
        self._backend_completion_flow = backend_completion_flow

        # Backend config service (already resolved in DI)
        self._backend_config_service = backend_config_provider

        # Wire capture (optional service)
        self._wire_capture: IWireCapture | None = wire_capture

        # Cancellation coordinator (optional service)
        self._cancellation_coordinator = cancellation_coordinator

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
        return _legacy_stream_formatting_service().stream_as_sse_bytes(stream)

    def _resolve_stream_session_id(
        self,
        session_id: str | None,
        context: RequestContext | None,
        request: ChatRequest,
    ) -> str:
        """Resolve a stable identifier for streaming capture and buffering.

        This is a thin wrapper method that delegates to the injected
        IStreamSessionIdResolver. Preserved for backward compatibility
        with existing tests that call this method directly.
        """
        return self._stream_session_id_resolver.resolve_stream_session_id(
            session_id=session_id,
            context=context,
            request=request,
        )

    def _get_failover_plan(
        self, model: str, backend_type: str
    ) -> list[tuple[str, str]]:
        """Return an ordered plan of (backend, model) attempts.

        This is a thin wrapper method that delegates to the injected
        IFailoverPlanner. Preserved for backward compatibility
        with existing tests that call this method directly.
        """
        return self._failover_planner.get_failover_plan(
            model=model,
            backend=backend_type,
        )

    def _filter_unhealthy_backends(
        self, plan: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        """Filter out backends with unhealthy API endpoints.

        This is a thin wrapper method that delegates to the internal
        filtering logic in IFailoverPlanner. Preserved for backward
        compatibility with existing tests that call this method directly.

        Args:
            plan: List of (backend, model) tuples

        Returns:
            Filtered list excluding unhealthy backends (if circuit breaker enabled)
        """
        # Delegate to the failover planner's public filtering method
        return self._failover_planner.filter_unhealthy_backends(plan)

    async def call_completion(
        self,
        request: ChatRequest,
        stream: bool = False,
        allow_failover: bool = True,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Call the LLM backend for a completion (delegates to BackendCompletionFlow)."""
        return await self._backend_completion_flow.call_completion(
            request=request,
            stream=stream,
            allow_failover=allow_failover,
            context=context,
        )

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
                    "Backend validation failed for %s: %s", backend, e, exc_info=True
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
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:  # type: ignore[override]
        """Handle chat completions with the LLM."""

        stream_raw = kwargs.get("stream", False)
        stream = bool(stream_raw) if stream_raw is not None else False

        allow_failover_raw = kwargs.get("allow_failover", True)
        allow_failover = (
            bool(allow_failover_raw) if allow_failover_raw is not None else True
        )
        context = cast(RequestContext | None, kwargs.get("context"))

        return await self.call_completion(
            request,
            stream=stream,
            allow_failover=allow_failover,
            context=context,
        )

    async def _resolve_backend_and_model(
        self, request: ChatRequest
    ) -> tuple[str, str, dict[str, Any]]:
        """Resolve backend type, effective model, and URI parameters from request and session.

        This is a thin wrapper method that delegates to the injected
        IBackendModelResolver. Preserved for backward compatibility
        with existing tests that call this method directly.
        """
        resolved = await self._backend_model_resolver.resolve_target(
            request=request,
            context=None,
        )
        return resolved.backend, resolved.model, resolved.uri_params

    def _synchronize_request_with_target(
        self, request: ChatRequest, backend_type: str, effective_model: str
    ) -> ChatRequest:
        """Ensure the request (and nested extra_body) reflect the backend/model chosen.

        This is a thin wrapper method that delegates to the injected
        IBackendModelResolver. Preserved for backward compatibility
        with existing tests that call this method directly.

        Args:
            request: Original chat request from the client.
            backend_type: Resolved backend name.
            effective_model: Resolved model name.

        Returns:
            A request object updated with the resolved backend/model information.
        """
        resolved = BackendTarget(
            backend=backend_type,
            model=effective_model,
            uri_params={},  # URI params not needed for synchronization
        )
        return self._backend_model_resolver.synchronize_request_with_target(
            request=request,
            resolved=resolved,
        )

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
        except (ValueError, TypeError, AttributeError, KeyError, IndexError):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("_detect_key_name failed", exc_info=True)
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "_detect_key_name failed unexpectedly: %s", str(e), exc_info=True
                )
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
        # Cancellation gate: ensure session is not cancelled before complex failover
        if self._cancellation_coordinator and context:
            from src.core.transport.session_key_resolver import (
                resolve_session_key_from_request_context,
            )

            session_key = resolve_session_key_from_request_context(context)
            if session_key:
                self._cancellation_coordinator.ensure_not_cancelled(session_key)

        if logger.isEnabledFor(logging.INFO):
            logger.info("Using complex failover policy for model %s", effective_model)
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
        # Cancellation gate: ensure session is not cancelled before failover plan execution
        if self._cancellation_coordinator and context:
            from src.core.transport.session_key_resolver import (
                resolve_session_key_from_request_context,
            )

            session_key = resolve_session_key_from_request_context(context)
            if session_key:
                self._cancellation_coordinator.ensure_not_cancelled(session_key)

        last_error: Exception | None = None
        if not plan:
            raise BackendError(message="all backends failed", backend_name=backend_type)

        for backend_attempt, model_attempt in plan:
            # Cancellation gate: ensure session is not cancelled before each failover attempt
            if self._cancellation_coordinator and context:
                from src.core.transport.session_key_resolver import (
                    resolve_session_key_from_request_context,
                )

                session_key = resolve_session_key_from_request_context(context)
                if session_key:
                    self._cancellation_coordinator.ensure_not_cancelled(session_key)

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
                        "Failover attempt failed for %s:%s: %s",
                        backend_attempt,
                        model_attempt,
                        attempt_error,
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
        uri_params: dict[str, JsonValue],
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
