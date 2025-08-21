"""
Models Controller

Handles model-related endpoints for the application.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

# Import HTTP status constants
from src.core.constants import HTTP_503_SERVICE_UNAVAILABLE_MESSAGE
from src.core.interfaces.backend_service_interface import IBackendService
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


async def get_backend_service(request: Request) -> IBackendService:
    """Get the backend service from the service provider.

    Args:
        request: The FastAPI request

    Returns:
        The backend service
    """
    if hasattr(request.app.state, "service_provider"):
        service_provider = request.app.state.service_provider
        service = service_provider.get_required_service(IBackendService)
        return service  # type: ignore[no-any-return]
    raise HTTPException(status_code=503, detail=HTTP_503_SERVICE_UNAVAILABLE_MESSAGE)


@router.get("/models")
async def list_models(
    request: Request,
    backend_service: IBackendService = Depends(get_backend_service),
) -> dict[str, Any]:
    """List available models from all configured backends.

    Returns:
        A dictionary containing the list of available models
    """
    try:
        logger.info("Listing available models")

        all_models: list[dict[str, Any]] = []
        discovered_models: set[str] = set()

        # Get app config from DI
        from src.core.config.app_config import AppConfig
        from src.core.interfaces.configuration_interface import IConfig
        from src.core.services.backend_factory_service import (
            BackendFactory,  # Import BackendFactory
        )

        config: AppConfig | None = None
        if hasattr(request.app.state, "service_provider"):
            try:
                config = request.app.state.service_provider.get_service(IConfig)
            except Exception:
                logger.warning("Failed to get config from service provider")

        if not config:
            # Fallback to default config
            config = AppConfig()

        # Get the backend factory instance
        backend_factory: BackendFactory = (
            request.app.state.service_provider.get_required_service(BackendFactory)
        )

        # Iterate through dynamically discovered backend types from the registry
        for backend_type in backend_registry.get_registered_backends():
            backend_config: Any | None = None
            if config.backends:
                # Access backend config dynamically using getattr
                backend_config = getattr(config.backends, backend_type, None)

            if backend_config and backend_config.api_key:
                try:
                    # Create backend instance
                    backend_instance: Any = backend_factory.create_backend(backend_type)

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

                except Exception as e: # type: ignore[misc]
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

        return {
            "object": "list",
            "data": all_models,
        }

    except Exception as e: # type: ignore[misc]
        logger.error(f"Error listing models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/v1/models")
async def list_models_v1(
    request: Request,
    backend_service: IBackendService = Depends(get_backend_service),
) -> dict[str, Any]:
    """OpenAI-compatible models endpoint.

    Returns:
        A dictionary containing the list of available models
    """
    return await list_models(request, backend_service)
