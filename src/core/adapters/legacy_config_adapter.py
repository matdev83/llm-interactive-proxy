"""
Legacy Config Adapter

Bridges the old configuration system with the new IConfig interface.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.interfaces.configuration import IConfig

logger = logging.getLogger(__name__)


class LegacyConfigAdapter(IConfig):
    """Adapter that wraps legacy configuration to implement IConfig interface."""
    
    def __init__(self, legacy_config: dict[str, Any]):
        """Initialize the adapter with legacy configuration.
        
        Args:
            legacy_config: The legacy configuration dictionary
        """
        self._legacy_config = legacy_config
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value.
        
        Args:
            key: The configuration key
            default: Default value if key not found
            
        Returns:
            The configuration value
        """
        return self._legacy_config.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Set a configuration value.
        
        Args:
            key: The configuration key
            value: The value to set
        """
        self._legacy_config[key] = value
    
    def has(self, key: str) -> bool:
        """Check if a configuration key exists.
        
        Args:
            key: The configuration key
            
        Returns:
            True if the key exists
        """
        return key in self._legacy_config
    
    def keys(self) -> list[str]:
        """Get all configuration keys.
        
        Returns:
            List of configuration keys
        """
        return list(self._legacy_config.keys())
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.
        
        Returns:
            Configuration as dictionary
        """
        return self._legacy_config.copy()
    
    def update(self, config: dict[str, Any]) -> None:
        """Update configuration with new values.
        
        Args:
            config: Configuration dictionary to merge
        """
        self._legacy_config.update(config)
    
    # Legacy-specific methods for backward compatibility
    
    @property
    def backend_type(self) -> str | None:
        """Get the backend type."""
        return self._legacy_config.get("backend")
    
    @property
    def command_prefix(self) -> str:
        """Get the command prefix."""
        return self._legacy_config.get("command_prefix", "!/")
    
    @property
    def proxy_timeout(self) -> int:
        """Get the proxy timeout."""
        return self._legacy_config.get("proxy_timeout", 300)
    
    @property
    def interactive_mode(self) -> bool:
        """Get the interactive mode setting."""
        return self._legacy_config.get("interactive_mode", True)
    
    @property
    def disable_auth(self) -> bool:
        """Get the disable auth setting."""
        return self._legacy_config.get("disable_auth", False)
    
    def get_backend_config(self, backend_type: str) -> dict[str, Any]:
        """Get configuration for a specific backend.
        
        Args:
            backend_type: The backend type
            
        Returns:
            Backend configuration dictionary
        """
        config = {}
        
        # Get API keys
        api_keys_key = f"{backend_type}_api_keys"
        if api_keys_key in self._legacy_config:
            config["api_keys"] = self._legacy_config[api_keys_key]
        
        # Get API base URL
        api_url_key = f"{backend_type}_api_base_url"
        if api_url_key in self._legacy_config:
            config["api_base_url"] = self._legacy_config[api_url_key]
        
        # Get timeout
        timeout_key = f"{backend_type}_timeout"
        if timeout_key in self._legacy_config:
            config["timeout"] = self._legacy_config[timeout_key]
        
        return config


def create_legacy_config_adapter(legacy_config: dict[str, Any]) -> LegacyConfigAdapter:
    """Create a legacy config adapter.
    
    Args:
        legacy_config: The legacy configuration dictionary
        
    Returns:
        A legacy config adapter
    """
    return LegacyConfigAdapter(legacy_config)