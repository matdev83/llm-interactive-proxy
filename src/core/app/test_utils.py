"""
Utility functions for testing.

This module provides helper functions for test applications.
"""

from __future__ import annotations

from typing import Any


def get_app_config_from_state(app: Any) -> Any:
    """
    Get app_config through IApplicationState interface if possible.

    This avoids direct app.state access and uses IApplicationState service when available.

    Args:
        app: The FastAPI application instance

    Returns:
        app_config object or None if not found/available
    """
    app_config = None
    # Get service provider if available
    service_provider = getattr(app, "state", None)
    if service_provider and hasattr(service_provider, "service_provider"):
        # Try to get AppConfig through IApplicationState
        try:
            from src.core.interfaces.application_state_interface import (
                IApplicationState,
            )

            app_state_service = service_provider.service_provider.get_service(
                IApplicationState
            )
            if app_state_service:
                app_config = app_state_service.get_setting("app_config")
        except (ImportError, AttributeError):
            pass

    # Fallback for legacy test code - this will be removed once all code is migrated
    if (
        app_config is None
        and hasattr(app, "state")
        and hasattr(app.state, "app_config")
    ):
        app_config = app.state.app_config

    return app_config
