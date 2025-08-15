"""
Adapter module to provide backward compatibility with the old config structure.

This module re-exports functions and classes from the new config structure
to maintain compatibility with code that imports from the old structure.
"""

from src.core.config import (
    AppConfig,
    _collect_api_keys,
    _keys_for,
    _load_config,
    get_openrouter_headers,
    load_config,
    logger,
)

# Re-export all the functions and classes
__all__ = [
    "AppConfig",
    "_collect_api_keys",
    "_keys_for",
    "_load_config",
    "get_openrouter_headers",
    "load_config",
    "logger",
]
