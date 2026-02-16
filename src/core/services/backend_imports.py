"""Module that triggers backend discovery during application startup."""

from src.core.services.backend_discovery import discover_backends

discover_backends()

__all__: list[str] = ["discover_backends"]
