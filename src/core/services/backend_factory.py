from __future__ import annotations

import logging
from typing import Any

import httpx

from src.connectors.base import LLMBackend
from src.core.interfaces.di_interface import IServiceProvider
from src.core.services.backend_registry import BackendRegistry

logger = logging.getLogger(__name__)


class BackendFactory:
    """Factory for creating LLM backends.

    This factory creates and configures backends based on type and configuration.
    """

    def __init__(
        self, httpx_client: httpx.AsyncClient, backend_registry: BackendRegistry
    ):
        """Initialize the backend factory.

        Args:
            httpx_client: HTTP client for API calls
            backend_registry: The registry for discovering backends
        """
        self._client = httpx_client
        self._backend_registry = backend_registry

    def create_backend(
        self, backend_type: str, api_key: str | None = None
    ) -> LLMBackend:
        """Create a backend instance of the specified type.

        Args:
            backend_type: The type of backend to create
            api_key: The API key to use for the backend (deprecated, use initialize_backend instead)

        Returns:
            A new LLM backend instance

        Raises:
            ValueError: If the backend type is not supported
        """
        backend_factory = self._backend_registry.get_backend_factory(backend_type)
        # Backend connectors only accept the client in constructor
        # API keys are set during initialization
        return backend_factory(self._client)

    async def initialize_backend(
        self, backend: LLMBackend, config: dict[str, Any]
    ) -> None:
        """Initialize a backend with configuration.

        Args:
            backend: The backend to initialize
            config: The configuration for the backend
        """
        await backend.initialize(**config)

    @staticmethod
    def create(service_provider: IServiceProvider) -> BackendFactory:
        """Create a backend factory using the service provider.

        This is a convenience method for dependency injection.

        Args:
            service_provider: The service provider to get dependencies from

        Returns:
            A new BackendFactory instance
        """
        client = service_provider.get_service(httpx.AsyncClient)
        if client is None:
            client = httpx.AsyncClient()

        backend_registry_instance = service_provider.get_required_service(
            BackendRegistry
        )
        return BackendFactory(client, backend_registry_instance)
