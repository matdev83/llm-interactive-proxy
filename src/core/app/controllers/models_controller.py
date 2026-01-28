"""
Models Controller

Handles model-related endpoints for the application.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from collections.abc import Awaitable
from typing import Any, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException

# Import HTTP status constants
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ConfigurationError,
    InitializationError,
    ServiceResolutionError,
    ServiceUnavailableError,
)
from src.core.constants import HTTP_503_SERVICE_UNAVAILABLE_MESSAGE
from src.core.domain.models_listing import ModelInfo, ModelsListingResponse
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

    async def list_models(self) -> ModelsListingResponse:
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
    except (KeyError, ServiceResolutionError, ImportError) as e:
        if logger.isEnabledFor(logging.WARNING):
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
            if logger.isEnabledFor(logging.DEBUG):
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
        if logger.isEnabledFor(logging.DEBUG):
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
            if logger.isEnabledFor(logging.DEBUG):
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
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "BackendFactory resolution via existing provider failed: %s",
                exc,
                exc_info=True,
            )

    from src.core.di.services import get_service_collection

    services = get_service_collection()
    translation: TranslationService | None = None
    provider_get_service = getattr(provider, "get_service", None)
    if callable(provider_get_service):
        translation = provider_get_service(TranslationService)  # type: ignore[assignment]
    else:
        try:
            translation = provider.get_required_service(TranslationService)
        except Exception as exc:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to resolve TranslationService from provider: %s",
                    exc,
                    exc_info=True,
                )
            translation = None
    if translation is not None:
        services.add_instance(TranslationService, translation)

    services.add_instance(BackendRegistry, backend_registry)

    new_provider = services.build_service_provider()
    try:
        return _resolve_backend_factory_from_provider(new_provider)
    except (ServiceResolutionError, InitializationError) as exc:
        if logger.isEnabledFor(logging.ERROR):
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
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "BackendFactory not registered; attempting to resolve via global provider"
            )
    raise ServiceResolutionError(
        "BackendFactory not registered in provider",
        details={"service": "BackendFactory"},
    )


def _check_backend_credentials(backend_config: Any) -> bool:
    """Check if backend has credentials configured."""
    if isinstance(backend_config, dict):
        return bool(backend_config.get("api_key"))
    if backend_config is None:
        return False
    api_key_value = getattr(backend_config, "api_key", None)
    if api_key_value:
        return True
    identity = getattr(backend_config, "identity", None)
    if identity is not None:
        return True
    extra = getattr(backend_config, "extra", None)
    if isinstance(extra, dict):
        credential_hints = {
            "credentials_path",
            "oauth_credentials_path",
            "token_path",
            "service_account_file",
        }
        return any(bool(extra.get(hint)) for hint in credential_hints)
    return False


def _check_opencode_zen_credentials(
    backend_factory: BackendFactory, config: IConfig
) -> bool:
    """Check if opencode-zen has credentials on disk."""
    import os
    import sys
    from pathlib import Path

    from src.core.config.app_config import AppConfig

    # Convert IConfig to AppConfig for create_backend
    app_config: AppConfig
    if isinstance(config, AppConfig):
        app_config = config
    else:
        app_config = AppConfig()

    temp_backend = None
    try:
        temp_backend = backend_factory.create_backend("opencode-zen", app_config)
        paths_to_check = []
        if sys.platform == "win32" or os.name == "nt":
            localappdata = os.environ.get("LOCALAPPDATA")
            if localappdata:
                paths_to_check.append(Path(localappdata) / "opencode" / "auth.json")
            paths_to_check.append(
                Path.home() / ".local" / "share" / "opencode" / "auth.json"
            )
        else:
            xdg_data_home = os.environ.get("XDG_DATA_HOME")
            if xdg_data_home:
                paths_to_check.append(Path(xdg_data_home) / "opencode" / "auth.json")
            paths_to_check.append(
                Path.home() / ".local" / "share" / "opencode" / "auth.json"
            )
        env_path = os.getenv("OPENCODE_AUTH_PATH")
        if env_path:
            paths_to_check.insert(0, Path(env_path))
        if any(p.exists() for p in paths_to_check):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Detected opencode-zen credentials on disk, enabling backend"
                )
            return True
    except Exception as e:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Failed to check opencode-zen credentials: %s", e, exc_info=True
            )
    finally:
        if temp_backend is not None:
            if hasattr(temp_backend, "close"):
                with contextlib.suppress(Exception):
                    temp_backend.close()  # type: ignore[attr-defined]
            elif hasattr(temp_backend, "aclose"):
                with contextlib.suppress(RuntimeError, Exception):
                    cleanup_task = asyncio.create_task(
                        temp_backend.aclose()  # type: ignore[attr-defined]
                    )
                    _ = cleanup_task
    return False


def _check_kiro_oauth_auto_credentials(config: Any) -> bool:
    """Check if kiro-oauth-auto has credentials on disk."""
    from pathlib import Path

    # Default path from KiroOAuthAutoConfig
    storage_path = "var/kiro_oauth_accounts"

    # Try to get from config if available
    backends = getattr(config, "backends", None)
    if backends:
        kiro_config = getattr(backends, "kiro-oauth-auto", None)
        if kiro_config and hasattr(kiro_config, "extra") and kiro_config.extra:
            storage_path = kiro_config.extra.get("storage_path", storage_path)

    p = Path(storage_path)
    if not p.is_dir():
        return False

    # Check for any .json files in the directory
    try:
        return any(f.suffix == ".json" for f in p.iterdir() if f.is_file())
    except Exception:
        return False


async def _get_backend_models(backend_instance: Any) -> list[str]:
    """Get available models from a backend instance."""
    get_models_async = getattr(backend_instance, "get_available_models_async", None)
    if callable(get_models_async):
        result: Any = await get_models_async()  # type: ignore[misc]
        if not isinstance(result, list):
            raise TypeError(
                "Backend get_available_models_async must return a list of model identifiers"
            )
        return cast(list[str], result)
    models_result = backend_instance.get_available_models()
    if inspect.isawaitable(models_result):
        awaited_result: Any = await cast(Awaitable[list[str]], models_result)
        if not isinstance(awaited_result, list):
            raise TypeError(
                "Backend get_available_models must return a list of model identifiers"
            )
        return cast(list[str], awaited_result)
    if not isinstance(models_result, list):
        raise TypeError(
            "Backend get_available_models must return a list of model identifiers"
        )
    return cast(list[str], models_result)


async def _list_models_impl(
    *,
    backend_service: IBackendService,
    config: IConfig,
    backend_factory: BackendFactory,
) -> ModelsListingResponse:
    """Shared implementation that discovers available models."""

    try:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Listing available models")

        all_models: list[ModelInfo] = []
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
            if logger.isEnabledFor(logging.DEBUG):
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

            has_credentials = _check_backend_credentials(backend_config)

            # Special case for backends that rely on disk-based credentials
            if (
                backend_type in ("opencode-zen", "kiro-oauth-auto")
                and not has_credentials
            ):
                from src.core.config.app_config import AppConfig

                # Use the provided config directly if it has the required structure
                if backend_type == "opencode-zen":
                    # opencode-zen check needs a proper AppConfig for create_backend
                    has_credentials = _check_opencode_zen_credentials(
                        backend_factory, config
                    )
                elif backend_type == "kiro-oauth-auto":
                    has_credentials = _check_kiro_oauth_auto_credentials(config)

            should_try_backend = backend_type in functional_backends or has_credentials

            if not should_try_backend:
                if logger.isEnabledFor(logging.DEBUG):
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

                # Ensure backend is initialized (especially important for opencode-zen which needs to load credentials)
                if hasattr(
                    backend_instance, "initialize"
                ) and inspect.iscoroutinefunction(backend_instance.initialize):
                    try:
                        await backend_instance.initialize()
                    except (ConfigurationError, AuthenticationError) as known_exc:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Skipping backend %s during model discovery: %s",
                                backend_type,
                                known_exc,
                            )
                        continue
                    except Exception as init_exc:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Failed to initialize backend %s: %s",
                                backend_type,
                                init_exc,
                                exc_info=True,
                            )
                        # Depending on the backend, failure to initialize might mean it's unusable.
                        # For opencode-zen, initialize sets is_functional.

                # Get available models from the backend
                models = await _get_backend_models(backend_instance)

                # Add models to the list with proper formatting
                for model in models:
                    model_id: str = (
                        f"{backend_type}:{model}" if backend_type != "openai" else model
                    )

                    # Avoid duplicates
                    if model_id not in discovered_models:
                        discovered_models.add(model_id)

                        # Look up context window from capabilities
                        from src.core.domain.model_capabilities import (
                            KNOWN_MODEL_CAPABILITIES,
                        )

                        # Try to find capabilities by model_id or base model name
                        capabilities = KNOWN_MODEL_CAPABILITIES.get(model_id)
                        base_model = (
                            model_id.split(":", 1)[-1] if ":" in model_id else model_id
                        )

                        if not capabilities:
                            # Try stripping backend prefix
                            capabilities = KNOWN_MODEL_CAPABILITIES.get(base_model)

                        if not capabilities:
                            # Try with provider prefixes
                            for prefix in ["google/", "openai/", "anthropic/"]:
                                capabilities = KNOWN_MODEL_CAPABILITIES.get(
                                    f"{prefix}{base_model}"
                                )
                                if capabilities:
                                    break

                        context_window = None
                        if capabilities and capabilities.limits:
                            context_window = capabilities.limits.context_window

                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Model discovery: id=%s, base=%s, cap_found=%s, context=%s",
                                model_id,
                                base_model,
                                capabilities is not None,
                                context_window,
                            )

                        all_models.append(
                            ModelInfo(
                                id=model_id,
                                object="model",
                                owned_by=(
                                    capabilities.backend_type
                                    if capabilities
                                    else str(backend_type).lower()
                                ),
                                context_window=context_window,
                            )
                        )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Discovered %d models from %s", len(models), backend_type
                    )

            except (ServiceUnavailableError, BackendError, httpx.RequestError) as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to get models from %s (known error): %s",
                        backend_type,
                        e,
                        exc_info=True,
                    )
                continue
            except Exception as e:  # type: ignore[misc]
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        "Unexpected error getting models from %s: %s",
                        backend_type,
                        e,
                        exc_info=True,
                    )
                continue

        # If no models were discovered, provide default fallback models
        if not all_models:
            if logger.isEnabledFor(logging.INFO):
                logger.info("No models discovered from backends, using default models")
            all_models = [
                ModelInfo(
                    id="gpt-4", object="model", owned_by="openai", context_window=8192
                ),
                ModelInfo(
                    id="gpt-3.5-turbo",
                    object="model",
                    owned_by="openai",
                    context_window=16385,
                ),
                ModelInfo(
                    id="claude-3-opus-20240229",
                    object="model",
                    owned_by="anthropic",
                    context_window=200000,
                ),
                ModelInfo(
                    id="claude-3-sonnet-20240229",
                    object="model",
                    owned_by="anthropic",
                    context_window=200000,
                ),
                ModelInfo(
                    id="gemini-1.5-pro",
                    object="model",
                    owned_by="google",
                    context_window=1048576,
                ),
                ModelInfo(
                    id="gemini-1.5-flash",
                    object="model",
                    owned_by="google",
                    context_window=1048576,
                ),
            ]

        if logger.isEnabledFor(logging.INFO):
            logger.info("Returning %d models", len(all_models))

        return ModelsListingResponse(object="list", data=all_models)

    except Exception as e:  # type: ignore[misc]
        if logger.isEnabledFor(logging.ERROR):
            logger.error("Error listing models: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/models")
async def list_models(
    backend_service: IBackendService = Depends(get_backend_service),
    config: IConfig = Depends(get_config_service),
    backend_factory: BackendFactory = Depends(get_backend_factory_service),
) -> ModelsListingResponse:
    """List available models from all configured backends."""

    return await _list_models_impl(
        backend_service=backend_service,
        config=config,
        backend_factory=backend_factory,
    )
