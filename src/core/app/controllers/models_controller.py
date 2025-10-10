"""
Models Controller

Handles model-related endpoints for the application.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException

# Import HTTP status constants
from src.core.common.exceptions import ServiceResolutionError
from src.core.constants import HTTP_503_SERVICE_UNAVAILABLE_MESSAGE
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.configuration_interface import IConfig
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_registry import (
    backend_registry,  # Updated import path
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["models"])


class ModelsController:
    """Controller for model-related endpoints."""

    def __init__(
        self,
        backend_service: IBackendService,
        config: IConfig | None = None,
        backend_factory: BackendFactory | None = None,
    ) -> None:
        """Initialize the models controller.

        Args:
            backend_service: The backend service to use
            config: Optional configuration service provided via DI
            backend_factory: Optional backend factory provided via DI
        """
        self.backend_service = backend_service
        self._config = config
        self._backend_factory = backend_factory

    async def list_models(self) -> dict[str, Any]:
        """List all available models using shared discovery logic."""

        config = self._config or get_config_service()
        backend_factory = self._backend_factory or get_backend_factory_service()

        return await _list_models_impl(
            backend_service=self.backend_service,
            config=config,
            backend_factory=backend_factory,
        )


async def get_backend_service() -> IBackendService:
    """Get the backend service from the DI container.

    Returns:
        The backend service

    Raises:
        HTTPException: If the service provider is not available
    """
    try:
        from src.core.di.services import get_service_provider

        service_provider = get_service_provider()
        service = service_provider.get_required_service(IBackendService)  # type: ignore[type-abstract]
        return service  # type: ignore[no-any-return]
    except Exception as e:
        logger.warning(
            "Global service provider unavailable: %s; trying request context",
            e,
            exc_info=True,
        )
        # Try to get from current request context (for FastAPI dependency injection)
        try:
            from starlette.context import _request_context  # type: ignore[import]

            if _request_context.exists():
                connection = _request_context.get()
                if hasattr(connection, "app") and hasattr(
                    connection.app.state, "service_provider"
                ):
                    service = connection.app.state.service_provider.get_required_service(IBackendService)  # type: ignore[type-abstract]
                    return service  # type: ignore[no-any-return]
        except Exception as ctx_err:
            logger.debug(
                "Request-context provider lookup failed: %s", ctx_err, exc_info=True
            )

        raise HTTPException(
            status_code=503, detail=HTTP_503_SERVICE_UNAVAILABLE_MESSAGE
        )


def get_config_service() -> IConfig:
    """Get the configuration service from the DI container.

    Returns:
        The configuration service
    """
    try:
        from src.core.di.services import get_service_provider

        service_provider = get_service_provider()
        return service_provider.get_required_service(IConfig)  # type: ignore[type-abstract,no-any-return]
    except KeyError as e:
        logger.debug(
            "IConfig not registered in global provider: %s; trying request context",
            e,
            exc_info=True,
        )
        # Try to get from current request context (for FastAPI dependency injection)
        try:
            from starlette.context import _request_context  # type: ignore[import]

            if _request_context.exists():
                connection = _request_context.get()
                if hasattr(connection, "app") and hasattr(
                    connection.app.state, "service_provider"
                ):
                    return connection.app.state.service_provider.get_required_service(IConfig)  # type: ignore[type-abstract,no-any-return]
        except Exception as ctx_err:
            logger.debug(
                "Request-context config lookup failed: %s", ctx_err, exc_info=True
            )

        # Final fallback to default config if IConfig is not registered (for testing)
        from src.core.config.app_config import AppConfig

        return AppConfig()  # type: ignore[no-any-return]


def get_backend_factory_service() -> BackendFactory:
    """Get the backend factory service.

    This function follows DIP principles by attempting to resolve the service
    through the DI container first, then falling back to direct creation
    using the same factory pattern as the rest of the application.

    Returns:
        The backend factory service
    """
    from src.core.di.services import get_or_build_service_provider

    # First, try to resolve the BackendFactory directly from the DI container.
    try:
        provider = get_or_build_service_provider()
        return _resolve_backend_factory_from_provider(provider)
    except Exception as exc:
        logger.debug(
            "Global BackendFactory resolution failed: %s", exc, exc_info=True
        )

    # Try to get from current request context (for FastAPI dependency injection)
    try:
        from starlette.context import _request_context  # type: ignore[import]

        if _request_context.exists():
            connection = _request_context.get()
            if hasattr(connection, "app") and hasattr(
                connection.app.state, "service_provider"
            ):
                return _resolve_backend_factory_from_provider(
                    connection.app.state.service_provider
                )
    except Exception as ctx_err:
        logger.debug(
            "Request-context BackendFactory lookup failed: %s",
            ctx_err,
            exc_info=True,
        )

    # If neither the global provider nor the request context could supply the
    # factory, surface an HTTP 503 so callers know the dependency graph is
    # misconfigured rather than silently constructing partial instances.
    raise HTTPException(status_code=503, detail=HTTP_503_SERVICE_UNAVAILABLE_MESSAGE)


def _resolve_backend_factory_from_provider(provider: Any) -> BackendFactory:
    """Resolve a BackendFactory using dependencies from the provider."""

    from src.core.config.app_config import AppConfig
    from src.core.services.backend_registry import BackendRegistry
    from src.core.services.translation_service import TranslationService

    import httpx

    try:
        return provider.get_required_service(BackendFactory)  # type: ignore[no-any-return]
    except (KeyError, ServiceResolutionError):
        logger.debug(
            "BackendFactory not registered; constructing from provider dependencies"
        )

    httpx_client = provider.get_required_service(httpx.AsyncClient)
    backend_registry_instance = provider.get_required_service(BackendRegistry)
    app_config = provider.get_required_service(AppConfig)
    translation_service = provider.get_required_service(TranslationService)

    return BackendFactory(
        httpx_client, backend_registry_instance, app_config, translation_service
    )


async def _list_models_impl(
    *,
    backend_service: IBackendService,
    config: IConfig,
    backend_factory: BackendFactory,
) -> dict[str, Any]:
    """Shared implementation that discovers available models."""

    try:
        logger.info("Listing available models")

        all_models: list[dict[str, Any]] = []
        discovered_models: set[str] = set()

        # Use the injected config service
        from src.core.config.app_config import AppConfig

        if not isinstance(config, AppConfig):
            # Fallback to default config if we got a different config type
            config = AppConfig()

        # Ensure backend service is at least resolved for DI side effects
        _ = backend_service

        try:
            functional_backends = set(config.backends.functional_backends)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.debug(
                "Unable to determine functional backends: %s", exc, exc_info=True
            )
            functional_backends = set()

        # Iterate through dynamically discovered backend types from the registry
        for backend_type in backend_registry.get_registered_backends():
            backend_config: Any | None = None
            if config.backends:
                # Access backend config dynamically using getattr
                backend_config = getattr(config.backends, backend_type, None)

            has_credentials = False
            if isinstance(backend_config, dict):
                has_credentials = bool(backend_config.get("api_key"))
            elif backend_config is not None:
                api_key_value = getattr(backend_config, "api_key", None)
                has_credentials = bool(api_key_value)
                if not has_credentials:
                    identity = getattr(backend_config, "identity", None)
                    extra = getattr(backend_config, "extra", None)
                    if identity is not None:
                        has_credentials = True
                    elif isinstance(extra, dict):
                        credential_hints = {
                            "credentials_path",
                            "oauth_credentials_path",
                            "token_path",
                            "service_account_file",
                        }
                        has_credentials = any(
                            bool(extra.get(hint)) for hint in credential_hints
                        )

            should_try_backend = backend_type in functional_backends or has_credentials

            if not should_try_backend:
                logger.debug(
                    "Skipping backend %s during model discovery: no credentials detected",
                    backend_type,
                )
                continue

            try:
                # Create backend instance
                backend_instance: Any = backend_factory.create_backend(
                    backend_type, config
                )

                # Get available models from the backend. Prefer async helper when available.
                models: list[str]
                get_models_async = getattr(
                    backend_instance, "get_available_models_async", None
                )
                if callable(get_models_async):
                    models = await get_models_async()  # type: ignore[misc]
                else:
                    models_result = backend_instance.get_available_models()
                    if inspect.isawaitable(models_result):
                        models = await cast(Awaitable[list[str]], models_result)
                    else:
                        if not isinstance(models_result, list):
                            raise TypeError(
                                "Backend get_available_models must return a list of model identifiers"
                            )
                        models = models_result

                # Add models to the list with proper formatting
                for model in models:
                    model_id: str = (
                        f"{backend_type}:{model}" if backend_type != "openai" else model
                    )

                    # Avoid duplicates
                    if model_id not in discovered_models:
                        discovered_models.add(model_id)
                        all_models.append(
                            {
                                "id": model_id,
                                "object": "model",
                                "owned_by": str(backend_type).lower(),
                            }
                        )
                logger.debug(f"Discovered {len(models)} models from {backend_type}")

            except Exception as e:  # type: ignore[misc]
                logger.warning(
                    f"Failed to get models from {backend_type}: {e}",
                    exc_info=True,
                )
                continue

        # If no models were discovered, provide default fallback models
        if not all_models:
            logger.info("No models discovered from backends, using default models")
            all_models = [
                {"id": "gpt-4", "object": "model", "owned_by": "openai"},
                {"id": "gpt-3.5-turbo", "object": "model", "owned_by": "openai"},
                {
                    "id": "claude-3-opus-20240229",
                    "object": "model",
                    "owned_by": "anthropic",
                },
                {
                    "id": "claude-3-sonnet-20240229",
                    "object": "model",
                    "owned_by": "anthropic",
                },
                {"id": "gemini-1.5-pro", "object": "model", "owned_by": "google"},
                {"id": "gemini-1.5-flash", "object": "model", "owned_by": "google"},
            ]

        logger.info(f"Returning {len(all_models)} models")

        return {"object": "list", "data": all_models}

    except Exception as e:  # type: ignore[misc]
        logger.error(f"Error listing models: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models")
async def list_models(
    backend_service: IBackendService = Depends(get_backend_service),
    config: IConfig = Depends(get_config_service),
    backend_factory: BackendFactory = Depends(get_backend_factory_service),
) -> dict[str, Any]:
    """List available models from all configured backends."""

    return await _list_models_impl(
        backend_service=backend_service,
        config=config,
        backend_factory=backend_factory,
    )
