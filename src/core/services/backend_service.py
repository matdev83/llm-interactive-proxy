from __future__ import annotations

import logging
from typing import Any, cast

from src.connectors.base import LLMBackend
from src.core.common.exceptions import BackendError, RateLimitExceededError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.failover_interface import (
    IFailoverCoordinator,
    IFailoverStrategy,
)
from src.core.interfaces.rate_limiter_interface import IRateLimiter
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.backend_factory import BackendFactory
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
        self._backends: dict[str, LLMBackend] = {}
        from src.core.config.app_config import AppConfig
        from src.core.services.failover_coordinator import FailoverCoordinator

        # Ensure config is properly typed for type checking
        _typed_config = cast(AppConfig, config)

        self._failover_service: FailoverService = FailoverService(failover_routes={})
        if failover_coordinator is None:
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
        self._failover_strategy: IFailoverStrategy | None = failover_strategy

    def _get_failover_plan(
        self, model: str, backend_type: str
    ) -> list[tuple[str, str]]:
        """Return an ordered plan of (backend, model) attempts.

        Uses the extracted strategy when enabled and available, otherwise falls
        back to coordinator-provided attempts.
        """
        use_strategy: bool = False
        try:
            use_strategy = self._app_state.get_use_failover_strategy()
        except Exception:
            use_strategy = False

        if use_strategy and self._failover_strategy is not None:
            try:
                return self._failover_strategy.get_failover_plan(model, backend_type)
            except Exception:
                # Fall back to coordinator attempts on error
                pass

        attempts = self._failover_coordinator.get_failover_attempts(model, backend_type)
        return [(a.backend, a.model) for a in attempts]

    async def call_completion(
        self, request: ChatRequest, stream: bool = False, allow_failover: bool = True
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Call the LLM backend for a completion."""
        # Resolve backend type and effective model
        backend_type, effective_model = await self._resolve_backend_and_model(request)

        request_failover_routes: dict[str, Any] | None = (
            request.extra_body.get("failover_routes") if request.extra_body else None
        )
        effective_failover_routes: dict[str, Any] = (
            request_failover_routes
            if request_failover_routes
            else self._failover_routes
        )

        # Handle complex failover if configured for this model
        if effective_model in effective_failover_routes:
            return await self._execute_complex_failover(
                request,
                effective_model,
                backend_type,
                effective_failover_routes,
                stream,
            )

        rate_key = f"backend:{backend_type}"
        limit_info = await self._rate_limiter.check_limit(rate_key)
        if limit_info.is_limited:
            raise RateLimitExceededError(
                message=f"Rate limit exceeded for {backend_type}",
                reset_at=limit_info.reset_at,
                limit=limit_info.limit,
                remaining=limit_info.remaining,
            )

        try:
            await self._rate_limiter.record_usage(rate_key)

            # Initialize backend only after passing rate limiting checks
            try:
                backend = await self._get_or_create_backend(backend_type)
            except Exception as e:
                raise BackendError(
                    message=f"Failed to initialize backend {backend_type}",
                    backend_name=backend_type,
                    details={"error": str(e)},
                )

            domain_request: ChatRequest = request

            domain_request = self._backend_config_service.apply_backend_config(
                domain_request, backend_type, cast(AppConfig, self._config)
            )

            try:
                app_config_typed: AppConfig = cast(AppConfig, self._config)
                backend_config_from_app = app_config_typed.backends.get(backend_type)
                identity = (
                    backend_config_from_app.identity
                    if backend_config_from_app and backend_config_from_app.identity
                    else app_config_typed.identity
                )
                result: ResponseEnvelope | StreamingResponseEnvelope = (
                    await backend.chat_completions(
                        request_data=domain_request,
                        processed_messages=request.messages,
                        effective_model=effective_model,
                        identity=identity,
                    )
                )

                return result
            except Exception as call_exc:
                # If the exception is already a BackendError or RateLimitExceededError,
                # treat it specially; otherwise wrap or re-raise depending on allow_failover.
                if isinstance(call_exc, BackendError | RateLimitExceededError):
                    if not allow_failover:
                        # Re-raise the original domain-specific exception
                        raise
                    last_error = call_exc
                else:
                    if not allow_failover:
                        # Immediate wrapping when failover is disabled
                        raise BackendError(
                            message=f"Backend call failed: {call_exc!s}",
                            backend_name=backend_type,
                        )
                    last_error = call_exc  # type: ignore[assignment]

                # Handle failover on backend call failure
                if allow_failover:
                    return await self._handle_backend_call_failover(
                        request, backend_type, stream, last_error
                    )

                # If we get here, wrap the last error into BackendError
                raise BackendError(
                    message=f"Backend call failed: {last_error!s}",
                    backend_name=backend_type,
                )

        except Exception:
            # Ensure the try/except block above is properly closed and
            # any unexpected exceptions are propagated as BackendError to
            # preserve the original behavior expected by tests.
            raise

    async def validate_backend_and_model(
        self, backend: str, model: str
    ) -> tuple[bool, str | None]:
        """Validate that a backend and model combination is valid."""
        try:
            backend_instance: LLMBackend = await self._get_or_create_backend(backend)

            available_models: list[str] = backend_instance.get_available_models()
            if model in available_models:
                return True, None

            return False, f"Model {model} not available on backend {backend}"
        except Exception as e:
            return False, f"Backend validation failed: {e!s}"

    async def _get_or_create_backend(self, backend_type: str) -> LLMBackend:
        """Get an existing backend or create a new one."""
        if backend_type in self._backends:
            return self._backends[backend_type]

        try:
            provider_cfg: Any | None = None
            if self._backend_config_provider:
                provider_cfg = self._backend_config_provider.get_backend_config(
                    backend_type
                )

            # Use provider config if available, otherwise use default app config
            from src.core.config.app_config import AppConfig

            if isinstance(provider_cfg, AppConfig):
                app_config = provider_cfg
            else:
                app_config = cast(AppConfig, self._config)

            # Cast provider_cfg to BackendConfig for type compatibility
            from src.core.config.app_config import BackendConfig

            backend_config = (
                provider_cfg
                if isinstance(provider_cfg, BackendConfig) or provider_cfg is None
                else None
            )
            backend: LLMBackend = await self._factory.ensure_backend(
                backend_type, app_config, backend_config
            )
            self._backends[backend_type] = backend
            return backend
        except Exception as e:
            raise BackendError(
                message=f"Failed to create backend {backend_type}: {e!s}",
                backend_name=backend_type,
            )

    async def chat_completions(
        self, request: ChatRequest, **kwargs: Any
    ) -> ResponseEnvelope | StreamingResponseEnvelope:  # type: ignore
        """Handle chat completions with the LLM."""
        stream = kwargs.get("stream", False)
        return await self.call_completion(request, stream=stream)

    async def _resolve_backend_and_model(self, request: ChatRequest) -> tuple[str, str]:
        """Resolve backend type and effective model from request and session."""
        session_id = (
            request.extra_body.get("session_id") if request.extra_body else None
        )
        session = (
            await self._session_service.get_session(session_id) if session_id else None
        )

        backend_type: str | None = None
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
        if not backend_type:
            from src.core.domain.model_utils import parse_model_backend

            app_config: AppConfig = cast(AppConfig, self._config)
            default_backend: str = (
                app_config.backends.default_backend
                if hasattr(app_config, "backends")
                else "openai"
            )
            parsed_backend, parsed_model = parse_model_backend(
                request.model, default_backend
            )
            backend_type = parsed_backend
            effective_model = parsed_model

        return backend_type, effective_model

    async def _execute_complex_failover(
        self,
        request: ChatRequest,
        effective_model: str,
        backend_type: str,
        effective_failover_routes: dict[str, Any],
        stream: bool,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute complex failover strategy for models with configured routes."""
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
                request, plan, stream, backend_type
            )
        except BackendError:
            raise
        except Exception as failover_error:
            logger.error(f"Failover processing failed: {failover_error!s}")
            raise BackendError(message="all backends failed", backend_name=backend_type)

    async def _attempt_failover_plan(
        self,
        request: ChatRequest,
        plan: list[tuple[str, str]],
        stream: bool,
        backend_type: str,
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
                    attempt_request, stream=stream, allow_failover=False
                )
            except Exception as attempt_error:
                logger.warning(
                    f"Failover attempt failed for {backend_attempt}:{model_attempt}: {attempt_error!s}"
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

    async def _handle_backend_call_failover(
        self,
        request: ChatRequest,
        backend_type: str,
        stream: bool,
        last_error: Exception,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Handle failover logic when backend call fails."""
        # Proceed with failover logic using last_error as the last seen exception
        request_failover_routes_nested: dict[str, Any] | None = (
            request.extra_body.get("failover_routes") if request.extra_body else None
        )
        effective_failover_routes_nested: dict[str, Any] = (
            request_failover_routes_nested
            if request_failover_routes_nested
            else self._failover_routes
        )

        if request.model in effective_failover_routes_nested:
            try:
                # Get the failover plan using the consolidated approach
                plan_nested: list[tuple[str, str]] = self._get_failover_plan(
                    request.model, backend_type
                )

                return await self._attempt_failover_plan(
                    request, plan_nested, stream, backend_type
                )
            except Exception as failover_error:
                logger.error(f"Failover processing failed: {failover_error!s}")
                raise BackendError(
                    message=f"Failover processing failed: {failover_error!s}",
                    backend_name=backend_type,
                )

        elif backend_type in self._failover_routes:
            fallback_info: dict[str, Any] = self._failover_routes.get(backend_type, {})
            fallback_backend: str | None = fallback_info.get("backend")
            fallback_model: str | None = fallback_info.get("model")

            if fallback_backend:
                logger.warning(
                    f"Primary backend {backend_type} failed with error: {last_error!s}. "
                    f"Attempting fallback to {fallback_backend}"
                )

                fallback_extra_body: dict[str, Any] = (
                    request.extra_body.copy() if request.extra_body else {}
                )
                fallback_extra_body["backend_type"] = fallback_backend

                fallback_updates: dict[str, Any] = {"extra_body": fallback_extra_body}
                if fallback_model:
                    fallback_updates["model"] = fallback_model

                fallback_request: ChatRequest = request.model_copy(
                    update=fallback_updates
                )

                return await self.call_completion(fallback_request, stream=stream)

        # If no failover options available, raise the original error
        raise BackendError(
            message=f"Backend call failed: {last_error!s}",
            backend_name=backend_type,
        )
