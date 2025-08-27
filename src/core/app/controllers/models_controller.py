"""
Models Controller

Handles model-related endpoints for the application.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

# Import HTTP status constants
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

    def __init__(self, backend_service: IBackendService) -> None:
        """Initialize the models controller.

        Args:
            backend_service: The backend service to use
        """
        self.backend_service = backend_service

    async def list_models(self) -> dict[str, Any]:
        """List all available models.

        Returns:
            Dictionary containing list of available models
        """
        # Implementation would go here
        # For now, return a basic response
        return {
            "object": "list",
            "data": [
                {"id": "gpt-4", "object": "model", "owned_by": "openai"},
                {"id": "gpt-3.5-turbo", "object": "model", "owned_by": "openai"},
            ],
        }


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
    except Exception:
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
        except Exception:
            pass

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
    except KeyError:
        # Try to get from current request context (for FastAPI dependency injection)
        try:
            from starlette.context import _request_context  # type: ignore[import]

            if _request_context.exists():
                connection = _request_context.get()
                if hasattr(connection, "app") and hasattr(
                    connection.app.state, "service_provider"
                ):
                    return connection.app.state.service_provider.get_required_service(IConfig)  # type: ignore[type-abstract,no-any-return]
        except Exception:
            pass

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
    # First, try to get from global service provider
    try:
        from src.core.di.services import get_service_provider
        from src.core.services.backend_factory import BackendFactory

        service_provider = get_service_provider()
        return service_provider.get_required_service(BackendFactory)  # type: ignore[no-any-return]
    except (KeyError, Exception):
        # Try to get from current request context (for FastAPI dependency injection)
        try:
            from starlette.context import _request_context  # type: ignore[import]

            if _request_context.exists():
                connection = _request_context.get()
                if hasattr(connection, "app") and hasattr(
                    connection.app.state, "service_provider"
                ):
                    return connection.app.state.service_provider.get_required_service(BackendFactory)  # type: ignore[no-any-return]
        except Exception:
            pass

        # Final fallback: create factory using the same pattern as BackendService
        # This ensures consistency with the DI container's factory methods
        import httpx

        from src.core.config.app_config import AppConfig
        from src.core.services.backend_factory import BackendFactory
        from src.core.services.backend_registry import backend_registry

        httpx_client = httpx.AsyncClient()
        config = AppConfig()  # Use default config as fallback
        return BackendFactory(httpx_client, backend_registry, config)


@router.get("/models")
async def list_models(
    backend_service: IBackendService = Depends(get_backend_service),
    config: IConfig = Depends(get_config_service),
    backend_factory: BackendFactory = Depends(get_backend_factory_service),
) -> dict[str, Any]:
    """List available models from all configured backends.

    Returns:
        A dictionary containing the list of available models
    """
    try:
        logger.info("Listing available models")

        all_models: list[dict[str, Any]] = []
        discovered_models: set[str] = set()

        # Use the injected config service
        from src.core.config.app_config import AppConfig

        if not isinstance(config, AppConfig):
            # Fallback to default config if we got a different config type
            config = AppConfig()

        # Iterate through dynamically discovered backend types from the registry
        for backend_type in backend_registry.get_registered_backends():
            backend_config: Any | None = None
            if config.backends:
                # Access backend config dynamically using getattr
                backend_config = getattr(config.backends, backend_type, None)

            if backend_config and backend_config.api_key:
                try:
                    # Create backend instance
                    backend_instance: Any = backend_factory.create_backend(
                        backend_type, config
                    )

                    # Get available models from the backend
                    models: list[str] = backend_instance.get_available_models()

                    # Add models to the list with proper formatting
                    for model in models:
                        model_id: str = (
                            f"{backend_type}:{model}"
                            if backend_type != "openai"
                            else model
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
                    logger.warning(f"Failed to get models from {backend_type}: {e}")
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
        logger.error(f"Error listing models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/v1/models")
async def list_models_v1(
    backend_service: IBackendService = Depends(get_backend_service),
    config: IConfig = Depends(get_config_service),
    backend_factory: BackendFactory = Depends(get_backend_factory_service),
) -> dict[str, Any]:
    """OpenAI-compatible models endpoint.

    Returns:
        A dictionary containing the list of available models
    """
    return await list_models(
        backend_service=backend_service, config=config, backend_factory=backend_factory
    )
