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
from src.core.common.exceptions import InitializationError, ServiceResolutionError
from src.core.constants import HTTP_503_SERVICE_UNAVAILABLE_MESSAGE
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.configuration_interface import IConfig
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_registry import (
    BackendRegistry,
    backend_registry,  # Updated import path
)
from src.core.services.translation_service import TranslationService

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
    except (KeyError, ServiceResolutionError) as e:
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
    provider = get_or_build_service_provider()
    try:
        return _resolve_backend_factory_from_provider(provider)
    except (HTTPException, ServiceResolutionError, InitializationError) as exc:
        logger.debug(
            "BackendFactory resolution via existing provider failed: %s",
            exc,
            exc_info=True,
        )

    from src.core.di.services import get_service_collection

    services = get_service_collection()
    translation = provider.get_service(TranslationService)
    if translation is not None:
        services.add_instance(TranslationService, translation)

    services.add_instance(BackendRegistry, backend_registry)

    new_provider = services.build_service_provider()
    try:
        return _resolve_backend_factory_from_provider(new_provider)
    except (ServiceResolutionError, InitializationError) as exc:
        logger.error(
            "BackendFactory resolution failed after rebuilding provider: %s",
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=503,
            detail=HTTP_503_SERVICE_UNAVAILABLE_MESSAGE,
        ) from exc


def _resolve_backend_factory_from_provider(provider: Any) -> BackendFactory:
    """Resolve a BackendFactory using dependencies from the provider."""

    try:
        return provider.get_required_service(BackendFactory)  # type: ignore[no-any-return]
    except (KeyError, ServiceResolutionError):
        logger.debug(
            "BackendFactory not registered; attempting to resolve via global provider"
        )

    # Try the existing global provider first
    try:
        from src.core.di.services import get_service_provider

        global_provider = get_service_provider()
    except Exception:
        global_provider = None

    if global_provider is not None and global_provider is not provider:
        backend_factory = global_provider.get_service(BackendFactory)
        if backend_factory is not None:
            return backend_factory

    # As a final fallback, rebuild the service provider via the global service collection
    try:
        from src.core.di.services import (
            get_service_collection,
            set_service_provider,
        )
    except ImportError as exc:  # pragma: no cover - defensive guard
        raise InitializationError("DI services unavailable") from exc

    services = get_service_collection()
    fallback_provider = services.build_service_provider()
    try:
        set_service_provider(fallback_provider)
    except Exception:
        logger.debug(
            "Failed to promote fallback provider to global scope", exc_info=True
        )

    backend_factory = fallback_provider.get_service(BackendFactory)
    if backend_factory is not None:
        return backend_factory

    raise InitializationError("BackendFactory unavailable after fallback resolution")


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

        # Determine which backend configuration views are available. Prefer the
        # injected configuration object but gracefully fall back to a default
        # AppConfig instance when the provided config does not expose a
        # compatible `backends` attribute. This preserves compatibility with
        # lightweight test doubles that only implement the public IConfig
        # interface while avoiding the previous behaviour of discarding the
        # injected configuration altogether.
        backend_views: list[Any] = []
        if hasattr(config, "backends"):
            try:
                backend_views.append(getattr(config, "backends"))
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.debug(
                    "Unable to access backends on %s: %s",
                    type(config).__name__,
                    exc,
                    exc_info=True,
                )
        else:
            logger.debug(
                "Configuration %s lacks 'backends' attribute; using fallback AppConfig",
                type(config).__name__,
            )

        if not backend_views:
            fallback_config = AppConfig()
            backend_views.append(fallback_config.backends)

        # Ensure backend service is at least resolved for DI side effects
        _ = backend_service

        functional_backends: set[str] = set()
        for view in backend_views:
            try:
                candidates = getattr(view, "functional_backends")
            except AttributeError:
                logger.debug(
                    "Backend configuration %s does not expose functional_backends",
                    type(view).__name__,
                )
                continue
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.debug(
                    "Error accessing functional_backends on %s: %s",
                    type(view).__name__,
                    exc,
                    exc_info=True,
                )
                continue

            # Support both property-based and plain attribute implementations.
            try:
                if callable(candidates):
                    candidates = candidates()
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.debug(
                    "Failed to invoke functional_backends on %s: %s",
                    type(view).__name__,
                    exc,
                    exc_info=True,
                )
                continue

            try:
                if isinstance(candidates, set) or isinstance(candidates, (list, tuple)):
                    functional_backends.update(candidates)
                elif isinstance(candidates, dict):
                    functional_backends.update(candidates.keys())
                elif candidates is None:
                    continue
                else:
                    functional_backends.update(set(candidates))
            except TypeError:
                logger.debug(
                    "functional_backends on %s is not iterable", type(view).__name__
                )
                continue

        # Iterate through dynamically discovered backend types from the registry
        for backend_type in backend_registry.get_registered_backends():
            backend_config: Any | None = None
            for view in backend_views:
                candidate: Any | None = None
                if isinstance(view, dict):
                    candidate = view.get(backend_type)
                else:
                    try:
                        candidate = getattr(view, backend_type, None)
                    except AttributeError:
                        candidate = None

                if candidate is not None:
                    backend_config = candidate
                    break

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
