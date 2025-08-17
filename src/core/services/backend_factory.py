from __future__ import annotations

import logging
from typing import Any

import httpx

from src.connectors.anthropic import AnthropicBackend
from src.connectors.base import LLMBackend
from src.connectors.gemini import GeminiBackend
from src.connectors.openai import OpenAIConnector
from src.connectors.openrouter import OpenRouterBackend
from src.connectors.qwen_oauth import QwenOAuthConnector
from src.connectors.zai import ZAIConnector
from src.constants import BackendType
from src.core.interfaces.di import IServiceProvider

logger = logging.getLogger(__name__)


class BackendFactory:
    """Factory for creating LLM backends.

    This factory creates and configures backends based on type and configuration.
    """

    def __init__(self, httpx_client: httpx.AsyncClient):
        """Initialize the backend factory.

        Args:
            httpx_client: HTTP client for API calls
        """
        self._client = httpx_client
        self._backend_types: dict[str, type[LLMBackend]] = {
            BackendType.OPENAI: OpenAIConnector,
            BackendType.OPENROUTER: OpenRouterBackend,
            BackendType.GEMINI: GeminiBackend,
            BackendType.ANTHROPIC: AnthropicBackend,
            BackendType.QWEN_OAUTH: QwenOAuthConnector,
            BackendType.ZAI: ZAIConnector,
        }

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
        if backend_type not in self._backend_types:
            raise ValueError(f"Unsupported backend type: {backend_type}")

        backend_class = self._backend_types[backend_type]
        # Backend connectors only accept the client in constructor
        # API keys are set during initialization
        return backend_class(self._client)

    async def initialize_backend(
        self, backend: LLMBackend, config: dict[str, Any]
    ) -> None:
        """Initialize a backend with configuration.

        Args:
            backend: The backend to initialize
            config: The configuration for the backend
        """
        await backend.initialize(**config)

    def register_backend_type(
        self, backend_type: str, backend_class: type[LLMBackend]
    ) -> None:
        """Register a new backend type.

        Args:
            backend_type: The type identifier for the backend
            backend_class: The backend class to register
        """
        self._backend_types[backend_type] = backend_class

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

        return BackendFactory(client)
