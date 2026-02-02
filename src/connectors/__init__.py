"""
Auto-discovery module for backend connectors.

This module automatically discovers and imports all backend connector modules
in this package, triggering their self-registration with the backend registry.

No hardcoded imports needed - just drop a new backend file in this directory
with backend_registry.register_backend() at module level, and it will be
automatically discovered and registered.

OAuth Connector Filtering:
In Multi User Mode, OAuth connectors are filtered out during auto-discovery
to prevent use of personal credentials in shared deployments.
"""

import importlib
import logging
import os
import pkgutil
from pathlib import Path

from .oauth_detector import is_oauth_connector

logger = logging.getLogger(__name__)

# Explicitly import base class first to ensure it's available
from .base import LLMBackend

__all__ = ["LLMBackend"]

# Auto-discover and import all backend modules
_current_dir = Path(__file__).parent

# Check access mode from environment variable (set by cli.py before import)
_access_mode = os.environ.get("LLM_PROXY_ACCESS_MODE", "single_user")
_is_multi_user_mode = _access_mode == "multi_user"

# Track OAuth connectors for logging
_skipped_oauth_connectors: list[str] = []
_loaded_oauth_connectors: list[str] = []

for module_info in pkgutil.iter_modules([str(_current_dir)]):
    module_name = module_info.name

    # Skip __init__, base, private modules, utility modules, and the mixins package
    skip_modules = (
        "__init__",
        "base",
        "streaming_utils",
        "mixins",
        "utils",
        "oauth_detector",
    )
    if module_name in skip_modules or module_name.startswith("_"):
        continue

    # OAuth connector filtering for Multi User Mode (Requirement 6.1, 6.2)
    if _is_multi_user_mode and is_oauth_connector(module_name):
        _skipped_oauth_connectors.append(module_name)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Skipping OAuth connector in Multi User Mode: %s", module_name)
        continue

    try:
        # Import the module to trigger backend registration side effects
        module = importlib.import_module(f".{module_name}", package=__package__)

        # Track loaded OAuth connectors in Single User Mode for logging
        if not _is_multi_user_mode and is_oauth_connector(module_name):
            _loaded_oauth_connectors.append(module_name)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Auto-discovered and imported backend module: %s", module_name)

        # SECURITY: Removed global namespace pollution via globals()
        # Previous code polluted global namespace during import time:
        # globals()[attr_name] = attr  # DANGEROUS - cross-boundary contamination
        # This violates test/production isolation like builtins injection
        # Use explicit imports instead of auto-exporting all discovered classes
    except Exception as e:
        # Log but don't fail - allow other backends to load
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to import backend module %s: %s", module_name, e, exc_info=True
            )

# Log OAuth connector filtering summary (Requirement 10.4, 10.5)
if _is_multi_user_mode and _skipped_oauth_connectors:
    logger.info(
        "Skipped %d OAuth connector(s) in Multi User Mode (OAuth not allowed in production): %s",
        len(_skipped_oauth_connectors),
        ", ".join(sorted(_skipped_oauth_connectors)),
    )
elif (
    not _is_multi_user_mode
    and _loaded_oauth_connectors
    and logger.isEnabledFor(logging.DEBUG)
):
    logger.debug(
        "Loaded %d OAuth connector(s) in Single User Mode: %s",
        len(_loaded_oauth_connectors),
        ", ".join(sorted(_loaded_oauth_connectors)),
    )


# Export skipped OAuth connectors for better error messages (Requirement 6.5)
def get_skipped_oauth_connectors() -> list[str]:
    """Get list of OAuth connectors skipped in Multi User Mode.

    Returns:
        List of connector names that were skipped due to OAuth filtering.
        Empty list in Single User Mode or if no connectors were skipped.
    """
    return _skipped_oauth_connectors.copy()


def is_running_in_multi_user_mode() -> bool:
    """Check if connector loading happened in Multi User Mode.

    Returns:
        True if Multi User Mode, False if Single User Mode.
    """
    return _is_multi_user_mode
