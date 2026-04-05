"""Module that triggers backend discovery during application startup."""

from src.core.services.backend_discovery import (
    discover_backends,
    reset_backend_discovery_state,
)

discover_backends()

__all__: list[str] = ["discover_backends", "reset_backend_discovery_state"]
