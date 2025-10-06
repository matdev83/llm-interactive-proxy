"""
Auto-discovery module for backend connectors.

This module automatically discovers and imports all backend connector modules
in this package, triggering their self-registration with the backend registry.

No hardcoded imports needed - just drop a new backend file in this directory
with backend_registry.register_backend() at module level, and it will be
automatically discovered and registered.
"""

import importlib
import logging
import pkgutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Explicitly import base class first to ensure it's available
from .base import LLMBackend

__all__ = ["LLMBackend"]

# Auto-discover and import all backend modules
_current_dir = Path(__file__).parent

for module_info in pkgutil.iter_modules([str(_current_dir)]):
    module_name = module_info.name

    # Skip __init__, base, private modules, and utility modules
    skip_modules = ("__init__", "base", "streaming_utils")
    if module_name in skip_modules or module_name.startswith("_"):
        continue

    try:
        # Import the module to trigger backend registration side effects
        module = importlib.import_module(f".{module_name}", package=__package__)
        logger.debug(f"Auto-discovered and imported backend module: {module_name}")

        # SECURITY: Removed global namespace pollution via globals()
        # Previous code polluted global namespace during import time:
        # globals()[attr_name] = attr  # DANGEROUS - cross-boundary contamination
        # This violates test/production isolation like builtins injection
        # Use explicit imports instead of auto-exporting all discovered classes
    except Exception as e:
        # Log but don't fail - allow other backends to load
        logger.warning(
            f"Failed to import backend module {module_name}: {e}", exc_info=True
        )
