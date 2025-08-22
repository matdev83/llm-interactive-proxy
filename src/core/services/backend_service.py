from __future__ import annotations

import logging
from typing import Any, cast

from src.connectors.base import LLMBackend
from src.core.common.exceptions import BackendError, RateLimitExceededError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import (
    ChatRequest,
)
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.rate_limiter_interface import IRateLimiter
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.backend_config_service import BackendConfigService
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
        backend_config_provider: IBackendConfigProvider | None = None,
        failover_routes: dict[str, dict[str, Any]] | None = None,
    ):
        """Initialize the backend service.

        Args:
            factory: The factory for creating backends
            rate_limiter: The rate limiter for API calls
            config: Application configuration
            session_service: The session service
            backend_configs: Configurations for backends
            failover_routes: Routes for backend failover
        """
        self._factory = factory
        self._rate_limiter = rate_limiter
        self._config = config
        self._session_service = session_service  # Store session_service
        self._backend_config_provider: IBackendConfigProvider | None = backend_config_provider
        self._backend_configs: dict[str, Any] = {}
        self._failover_routes: dict[str, dict[str, Any]] = failover_routes or {}
        self._backends: dict[str, LLMBackend] = {}
        cast(AppConfig, config)
        from src.core.services.failover_coordinator import FailoverCoordinator

        self._failover_service: FailoverService = FailoverService(failover_routes={})
        self._failover_coordinator: FailoverCoordinator = FailoverCoordinator(self._failover_service)
        self._backend_config_service: BackendConfigService = BackendConfigService()

    async def call_completion(
        self, request: ChatRequest, stream: bool = False, allow_failover: bool = True
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Call the LLM backend for a completion."""
        session_id = request.extra_body.get("session_id") if request.extra_body else None
        session = await self._session_service.get_session(session_id) if session_id else None

        backend_type: str | None = None
        if session and session.state and session.state.backend_config:
            from src.core.domain.configuration.backend_config import (
                BackendConfiguration,
            )
            backend_type = cast(BackendConfiguration, session.state.backend_config).backend_type

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

        request_failover_routes: dict[str, Any] | None = (
            request.extra_body.get("failover_routes") if request.extra_body else None
        )
        effective_failover_routes: dict[str, Any] = (
            request_failover_routes
            if request_failover_routes
            else self._failover_routes
        )

        if effective_model in effective_failover_routes:
            logger.info(f"Using complex failover policy for model {effective_model}")
            try:
                from src.core.domain.configuration.backend_config import (
                    BackendConfiguration,
                )

                backend_config: BackendConfiguration = BackendConfiguration(
                    backend_type=backend_type,
                    model=effective_model,
                    failover_routes_data=effective_failover_routes,
                )

                attempts: list[Any] = self._failover_coordinator.get_failover_attempts(
                    effective_model, backend_type
                )

                if not attempts:
                    raise BackendError(
                        message="all backends failed", backend_name=backend_type
                    )

                for attempt in attempts:
                    try:
                        attempt_extra_body: dict[str, Any] = (
                            request.extra_body.copy() if request.extra_body else {}
                        )
                        attempt_extra_body["backend_type"] = attempt.backend

                        attempt_request: ChatRequest = request.model_copy(
                            update={
                                "extra_body": attempt_extra_body,
                                "model": attempt.model,
                            }
                        )

                        return await self.call_completion(
                            attempt_request, stream=stream, allow_failover=False
                        )
                    except Exception as attempt_error:
                        logger.warning(
                            f"Failover attempt failed for {attempt.backend}:{attempt.model}: {attempt_error!s}"
                        )
                        last_error = attempt_error
                        continue

                if 'last_error' in locals():
                    raise BackendError(
                        message=f"All failover attempts failed. Last error: {last_error!s}",
                        backend_name=backend_type,
                    )
                else:
                    raise BackendError(
                        message="All failover attempts failed. No error details available.",
                        backend_name=backend_type,
                    )
            except BackendError:
                raise
            except Exception as failover_error:
                logger.error(f"Failover processing failed: {failover_error!s}")
                raise BackendError(
                    message="all backends failed", backend_name=backend_type
                )

        try:
            backend = await self._get_or_create_backend(backend_type)
        except Exception as e:
            raise BackendError(
                message=f"Failed to initialize backend {backend_type}",
                backend_name=backend_type,
                details={"error": str(e)},
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

            domain_request: ChatRequest = request

            domain_request = self._backend_config_service.apply_backend_config(
                domain_request, backend_type, cast(AppConfig, self._config)
            )

            try:
                result: ResponseEnvelope | StreamingResponseEnvelope = await backend.chat_completions(
                    request_data=domain_request,
                    processed_messages=request.messages,
                    effective_model=effective_model,
                )

                return result
            except Exception as call_exc:
                # If the exception is already a BackendError or RateLimitExceededError,
                # treat it specially; otherwise wrap or re-raise depending on allow_failover.
                if isinstance(call_exc, (BackendError, RateLimitExceededError)):
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
                    last_error = call_exc

                # Proceed with failover logic using last_error as the last seen exception
                request_failover_routes_nested: dict[str, Any] | None = (
                    request.extra_body.get("failover_routes") if request.extra_body else None
                )
                effective_failover_routes_nested: dict[str, Any] = (
                    request_failover_routes_nested if request_failover_routes_nested else self._failover_routes
                )

                if request.model in effective_failover_routes_nested:
                    try:
                        from src.core.domain.configuration.backend_config import (
                            BackendConfiguration,
                        )

                        backend_config_nested: BackendConfiguration = BackendConfiguration(
                            backend_type=backend_type,
                            model=request.model,
                            failover_routes_data=effective_failover_routes_nested,
                        )

                        attempts_nested: list[Any] = self._failover_service.get_failover_attempts(
                            backend_config_nested, request.model, backend_type
                        )

                        if not attempts_nested:
                            raise BackendError(
                                message=f"No failover attempts available for model {request.model}",
                                backend_name=backend_type,
                            )

                        last_error_nested: Exception | None = None
                        for attempt in attempts_nested:
                            try:
                                attempt_extra_body_nested: dict[str, Any] = (
                                    request.extra_body.copy() if request.extra_body else {}
                                )
                                attempt_extra_body_nested["backend_type"] = attempt.backend

                                attempt_request_nested: ChatRequest = request.model_copy(
                                    update={
                                        "extra_body": attempt_extra_body_nested,
                                        "model": attempt.model,
                                    }
                                )

                                return await self.call_completion(
                                    attempt_request_nested, stream=stream, allow_failover=False
                                )
                            except Exception as attempt_error:
                                logger.warning(
                                    f"Failover attempt failed for {attempt.backend}:{attempt.model}: {attempt_error!s}"
                                )
                                last_error_nested = attempt_error
                                continue

                        if last_error_nested:
                            raise BackendError(
                                message=f"All failover attempts failed: {last_error_nested!s}",
                                backend_name=backend_type,
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

                        fallback_request: ChatRequest = request.model_copy(update=fallback_updates)

                        return await self.call_completion(fallback_request, stream=stream)

                # If we get here, wrap the last error into BackendError
                raise BackendError(
                    message=f"Backend call failed: {last_error!s}", backend_name=backend_type
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

            backend: LLMBackend = await self._factory.ensure_backend(backend_type, provider_cfg)
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
