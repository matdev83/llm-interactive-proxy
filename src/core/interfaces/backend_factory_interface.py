from __future__ import annotations

from abc import abstractmethod
from typing import Any, Protocol

from src.connectors.base import LLMBackend
from src.core.config.app_config import AppConfig, BackendConfig


class IBackendFactory(Protocol):
    """Interface for creating and managing LLM backends."""

    @abstractmethod
    def create_backend(
        self, backend_type: str, config: AppConfig | None = None
    ) -> LLMBackend:
        """Create a backend instance of the specified type."""
        ...

    @abstractmethod
    async def initialize_backend(
        self, backend: LLMBackend, init_config: dict[str, Any]
    ) -> None:
        """Initialize a backend with configuration."""
        ...

    @abstractmethod
    async def ensure_backend(
        self,
        backend_type: str,
        app_config: AppConfig,
        backend_config: BackendConfig | None = None,
    ) -> LLMBackend:
        """Create and initialize a backend given a canonical BackendConfig."""
        ...
