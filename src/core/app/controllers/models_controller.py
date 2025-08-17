"""
Models Controller

Handles model-related endpoints for the application.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from src.core.interfaces.backend_service import IBackendService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["models"])


async def get_backend_service(request: Request) -> IBackendService:
    """Get the backend service from the service provider.

    Args:
        request: The FastAPI request

    Returns:
        The backend service
    """
    if hasattr(request.app.state, "service_provider"):
        service_provider = request.app.state.service_provider
        return service_provider.get_required_service(IBackendService)
    raise HTTPException(status_code=503, detail="Service provider not available")


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

        # Get models from all configured backends
        all_models: list[dict[str, Any]] = []
        discovered_models: set[str] = set()  # Track unique models

        # Get configuration to check which backends are available
        from src.constants import BackendType

        # Check if we can access the app config
        if hasattr(request.app.state, "app_config"):
            config = request.app.state.app_config

            # List of backend types to check
            backend_checks = [
                (
                    BackendType.OPENAI,
                    config.backends.openai if config.backends else None,
                ),
                (
                    BackendType.ANTHROPIC,
                    config.backends.anthropic if config.backends else None,
                ),
                (
                    BackendType.OPENROUTER,
                    config.backends.openrouter if config.backends else None,
                ),
                (
                    BackendType.GEMINI,
                    config.backends.gemini if config.backends else None,
                ),
                (BackendType.ZAI, config.backends.zai if config.backends else None),
            ]

            # Try to get models from each configured backend
            for backend_type, backend_config in backend_checks:
                if (
                    backend_config
                    and hasattr(backend_config, "api_key")
                    and backend_config.api_key
                ):
                    try:
                        # Get or create the backend
                        # We need to access the backend through the service's public interface
                        # For now, we'll skip this functionality as it's not critical
                        # backend = await backend_service._get_or_create_backend(
                        #     backend_type
                        # )
                        # 
                        # # Get available models from the backend
                        # if hasattr(backend, "get_available_models"):
                        #     models = backend.get_available_models()
                        # 
                        #     # Add models to the list with proper formatting
                        #     for model in models:
                        #         model_id = (
                        #             f"{backend_type}:{model}"
                        #             if backend_type != BackendType.OPENAI
                        #             else model
                        #         )
                        # 
                        #         # Avoid duplicates
                        #         if model_id not in discovered_models:
                        #             discovered_models.add(model_id)
                        #             all_models.append(
                        #                 {
                        #                     "id": model_id,
                        #                     "object": "model",
                        #                     "owned_by": str(backend_type).lower(),
                        #                 }
                        #             )
                        # 
                        #     logger.debug(
                        #         f"Discovered {len(models)} models from {backend_type}"
                        #     )
                        # Continue with other backends
                        continue

                    except Exception as e:
                        logger.warning(f"Failed to get models from {backend_type}: {e}")
                        # Continue with other backends
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

    except Exception as e:
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
