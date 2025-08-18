"""
Integration bridge shim.

The original IntegrationBridge was part of the migration scaffolding and
provided helpers to initialize legacy components. During the SOLID refactor
we moved to direct DI and modern services; keeping a large bridge class
reintroduces legacy coupling. This module now exposes a lightweight shim
that stores and returns a service provider if one is set on the FastAPI
app state. Tests that previously relied on the bridge should use the
service provider APIs directly or use the shim to access `app.state.service_provider`.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

# This shim intentionally provides a minimal, test-friendly API.

_bridge_instance: FastAPI | None = None


def set_integration_bridge(app: FastAPI) -> None:
    """Register the FastAPI app as the current bridge target.

    Tests or earlier plumbing can call this to provide access to the
    application's `state.service_provider` without importing legacy APIs.
    """
    global _bridge_instance
    _bridge_instance = app


def get_integration_bridge(app: FastAPI | None = None) -> FastAPI | None:
    """Return the registered FastAPI app used as the integration bridge.

    If `app` is provided during the first call it will be stored and
    returned on subsequent calls. Otherwise returns the previously
    registered app or None.
    """
    global _bridge_instance
    if _bridge_instance is None and app is not None:
        _bridge_instance = app
    return _bridge_instance


# Note: no alias re-definition. `set_integration_bridge` defined above is the canonical implementation.


class IntegrationBridge:
    """Lightweight compatibility IntegrationBridge.

    This class exists to provide a minimal, test-friendly API for tests that
    still instantiate an IntegrationBridge. It intentionally does not contain
    legacy initialization logic; prefer using DI and `app.state.service_provider`.
    """

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.new_initialized: bool = False
        self.legacy_initialized: bool = False

    async def initialize_new_architecture(self) -> None:
        """Mark the new architecture as initialized and register the app."""
        # Register the app so get_integration_bridge() can find it
        set_integration_bridge(self.app)
        self.new_initialized = True

    def get_service_provider(self) -> Any:
        return getattr(self.app.state, "service_provider", None)

    async def sync_session(self, session_id: str) -> None:
        """No-op sync placeholder. Real sync should be handled by migration service."""
        # Intentionally minimal: migration is handled by services via DI
        return

    async def cleanup(self) -> None:
        self.new_initialized = False
        self.legacy_initialized = False
