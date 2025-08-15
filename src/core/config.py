"""
Configuration module that provides backward compatibility.

This module re-exports configuration functions and classes from the new
config structure to maintain compatibility with existing code.
"""

from src.core.config.app_config import AppConfig, load_config
from src.core.config.config_loader import (
    _collect_api_keys,
    _keys_for,
    _load_config,
    get_openrouter_headers,
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