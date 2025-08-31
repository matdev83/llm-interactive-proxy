from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from src.connectors.base import LLMBackend
from src.core.config.app_config import AppConfig, BackendConfig
from src.core.interfaces.di_interface import IServiceProvider
from src.core.services.backend_registry import BackendRegistry
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class BackendFactory:
    """Factory for creating LLM backends.

    This factory creates and configures backends based on type and configuration.
    """

    def __init__(
        self,
        httpx_client: httpx.AsyncClient,
        backend_registry: BackendRegistry,
        config: AppConfig,
        translation_service: TranslationService,
    ) -> None:
        """Initialize the backend factory.

        Args:
            httpx_client: HTTP client for API calls
            backend_registry: The registry for discovering backends
            config: The application configuration
        """
        self._client = httpx_client
        self._backend_registry = backend_registry
        self._config = config  # Stored config
        self._translation_service = translation_service

    def create_backend(
        self, backend_type: str, config: AppConfig  # Added config
    ) -> LLMBackend:
        """Create a backend instance of the specified type.

        Args:
            backend_type: The type of backend to create
            config: The application configuration

        Returns:
            A new LLM backend instance

        Raises:
            ValueError: If the backend type is not supported
        """
        backend_factory = self._backend_registry.get_backend_factory(backend_type)
        # Backend connectors only accept the client and config in constructor
        return backend_factory(
            self._client, self._config, self._translation_service
        )  # Modified

    async def initialize_backend(
        self, backend: LLMBackend, init_config: dict[str, Any]
    ) -> None:
        """Initialize a backend with configuration.

        Args:
            backend: The backend to initialize
            init_config: The configuration for the backend
        """
        await backend.initialize(**init_config)

    async def ensure_backend(
        self,
        backend_type: str,
        app_config: AppConfig,  # Added app_config
        backend_config: BackendConfig | None = None,
    ) -> LLMBackend:
        """Create and initialize a backend given a canonical BackendConfig.

        This method centralizes connector initialization logic so callers
        don't need to duplicate api_key/url shaping and backend-specific
        parameters.
        """
        logger = logging.getLogger(__name__)

        # Build init_config from BackendConfig
        init_config: dict[str, Any] = {}

        if backend_config is not None:
            api_key_list = backend_config.api_key
            init_config["api_key"] = api_key_list[0] if api_key_list else None
            if backend_config.api_url:
                init_config["api_base_url"] = backend_config.api_url
            for k, v in backend_config.extra.items():
                init_config[k] = v

        # Handle test env: add dummy key when running pytest and no key present
        default_backend_env = os.environ.get("LLM_BACKEND")
        if os.environ.get("PYTEST_CURRENT_TEST") and (
            not init_config.get("api_key")
            and (not default_backend_env or default_backend_env == backend_type)
        ):
            init_config["api_key"] = f"test-key-{backend_type}"
            logger.info(f"Added test API key for {backend_type} in factory")

        # Backend-specific augmentations
        if backend_type == "anthropic":
            init_config["key_name"] = backend_type
        elif backend_type == "openrouter":
            from src.core.config.config_loader import get_openrouter_headers

            init_config["key_name"] = backend_type
            init_config["openrouter_headers_provider"] = get_openrouter_headers
            if "api_base_url" not in init_config:
                init_config["api_base_url"] = "https://openrouter.ai/api/v1"
        elif backend_type == "gemini":
            init_config["key_name"] = backend_type
            if "api_base_url" not in init_config:
                init_config["api_base_url"] = (
                    "https://generativelanguage.googleapis.com"
                )

        logger.info(f"Factory initializing backend {backend_type} with {init_config}")

        # Step 1: Create the backend instance
        backend = self.create_backend(backend_type, app_config)  # Modified

        # Step 2: Initialize it with the config
        await self.initialize_backend(backend, init_config)

        return backend

    @staticmethod
    def create(service_provider: IServiceProvider) -> BackendFactory:
        """Create a backend factory using the service provider.

        This is a convenience method for dependency injection.

        Args:
            service_provider: The service provider to get dependencies from

        Returns:
            A new BackendFactory instance
        """
        # Resolve the registered BackendFactory from the DI container
        # to avoid manual instantiation and adhere to DIP.
        return service_provider.get_required_service(BackendFactory)
