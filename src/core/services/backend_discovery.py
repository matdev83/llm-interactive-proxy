"""Unified backend discovery orchestration.

Discovers built-in core connectors first, then optional plugin connectors.
"""

from __future__ import annotations

import logging
from importlib import import_module

from src.core.services.backend_plugin_discovery import discover_plugin_backends
from src.core.services.backend_registry import backend_registry

logger = logging.getLogger(__name__)


def discover_backends() -> None:
    """Populate backend registry from core connectors and optional plugins."""
    import_module("src.connectors")
    discovered_plugin_backends = discover_plugin_backends()
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "Backend discovery complete. Plugins discovered: %s. Registered backends: %s",
            discovered_plugin_backends,
            backend_registry.get_registered_backends(),
        )
