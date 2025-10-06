from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from src.core.config.app_config import AppConfig, BackendConfigModel
from src.core.domain.chat import ChatRequest


@runtime_checkable
class IBackendConfigProvider(Protocol):
    """Interface for providing normalized backend configuration to services.

    Implementations must return canonical `BackendConfigModel` objects so callers
    do not need to handle mixed shapes (dict vs BackendConfigModel).
    """

    def get_backend_config(self, name: str) -> BackendConfigModel | None:
        """Return the `BackendConfigModel` for the given backend name or None."""

    def iter_backend_names(self) -> Iterable[str]:
        """Iterate over known backend names."""

    def get_default_backend(self) -> str:
        """Return the configured default backend name."""

    def get_functional_backends(self) -> set[str]:
        """Return a set of backend names that are considered functional (e.g. have API keys)."""

    def apply_backend_config(
        self, request: ChatRequest, backend_type: str, config: AppConfig
    ) -> ChatRequest:
        """Apply backend-specific configuration to a request.

        Args:
            request: The chat completion request
            backend_type: The backend type
            config: The application configuration

        Returns:
            The updated request with backend-specific configuration applied
        """
