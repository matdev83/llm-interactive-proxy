from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from src.core.config.app_config import BackendConfig


@runtime_checkable
class IBackendConfigProvider(Protocol):
    """Interface for providing normalized backend configuration to services.

    Implementations must return canonical `BackendConfig` objects so callers
    do not need to handle mixed shapes (dict vs BackendConfig).
    """

    def get_backend_config(self, name: str) -> BackendConfig | None:
        """Return the `BackendConfig` for the given backend name or None."""

    def iter_backend_names(self) -> Iterable[str]:
        """Iterate over known backend names."""

    def get_default_backend(self) -> str:
        """Return the configured default backend name."""

    def get_functional_backends(self) -> set[str]:
        """Return a set of backend names that are considered functional (e.g. have API keys)."""
