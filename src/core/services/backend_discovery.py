"""Unified backend discovery orchestration.

Discovers built-in core connectors first, then optional plugin connectors.
"""

from __future__ import annotations

import logging
from importlib import import_module, metadata

from src.core.common.backend_discovery_state import (
    filter_oauth_style_backend_names,
    get_oauth_install_command,
    get_optional_oauth_package_name,
)
from src.core.services.backend_plugin_discovery import discover_plugin_backends
from src.core.services.backend_registry import backend_registry

logger = logging.getLogger(__name__)


def _log_oauth_package_status() -> None:
    """Log OAuth connectors package presence and supported backends at startup.

    Enumerates from the live backend registry only; filters by structural
    naming convention (*-oauth, *-oauth-*). No hardcoded backend names.
    """
    optional_package = get_optional_oauth_package_name()
    install_command = get_oauth_install_command()
    registered = backend_registry.get_registered_backends()
    oauth_backends = filter_oauth_style_backend_names(registered)
    try:
        metadata.version(optional_package)
        pkg_installed = True
    except metadata.PackageNotFoundError:
        pkg_installed = False

    if oauth_backends:
        logger.info(
            "OAuth connectors package installed. Supported backends: %s",
            ", ".join(oauth_backends),
        )
    elif pkg_installed:
        logger.info(
            "OAuth connectors package installed. No backends available "
            "(may be blocked in Multi User Mode)."
        )
    else:
        logger.info(
            "OAuth connectors package not installed. Install with: %s (optional)",
            install_command,
        )


def discover_backends() -> None:
    """Populate backend registry from core connectors and optional plugins."""
    import_module("src.connectors")
    discovered_plugin_backends = discover_plugin_backends()
    if logger.isEnabledFor(logging.INFO):
        _log_oauth_package_status()
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "Backend discovery complete. Plugins discovered: %s. Registered backends: %s",
            discovered_plugin_backends,
            backend_registry.get_registered_backends(),
        )
