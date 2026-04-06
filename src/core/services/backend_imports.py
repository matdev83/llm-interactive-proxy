"""Module that triggers backend discovery during application startup."""

from __future__ import annotations

from src.core.services.backend_discovery import discover_backends

discover_backends()


def reset_backend_discovery_state() -> None:
    """Reset discovery idempotency (re-export for tests and tooling)."""
    from src.core.services.backend_discovery import (
        reset_backend_discovery_state as _reset,
    )

    _reset()


__all__: list[str] = ["discover_backends", "reset_backend_discovery_state"]
