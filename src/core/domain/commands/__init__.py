"""
Commands domain module with auto-discovery.

This module automatically discovers and imports all command modules in this package,
triggering their self-registration with the domain command registry.

No hardcoded imports needed - just drop a new command file in this directory
with domain_command_registry.register_command() calls at module level, and it will be
automatically discovered and registered.
"""

import importlib
import logging
import pkgutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Import only the base command to avoid circular imports
from src.core.domain.commands.base_command import BaseCommand

# CommandResult is in the parent command_results.py module
from ..command_results import CommandResult

__all__ = ["BaseCommand", "CommandResult"]

# Auto-discover and import all command modules
_current_dir = Path(__file__).parent

for module_info in pkgutil.iter_modules([str(_current_dir)]):
    module_name = module_info.name

    # Skip __init__, base classes, registry, and private modules
    skip_modules = (
        "__init__",
        "base_command",
        "secure_base_command",
        "command_registry",
    )
    if module_name in skip_modules or module_name.startswith("_"):
        continue

    # Skip subdirectories for now (they have their own __init__.py)
    if module_info.ispkg:
        continue

    try:
        # Import the module to trigger command registration side effects
        module = importlib.import_module(f".{module_name}", package=__package__)
        logger.debug(f"Auto-discovered and imported command module: {module_name}")

        # SECURITY: Removed global namespace pollution via globals()
        # Previous code polluted global namespace during import time:
        # globals()[attr_name] = attr  # DANGEROUS - cross-boundary contamination
        # This violates test/production isolation like builtins injection
        # Use explicit imports instead of auto-exporting all discovered classes
    except Exception as e:
        # Log but don't fail - allow other commands to load
        logger.warning(
            f"Failed to import command module {module_name}: {e}", exc_info=True
        )
