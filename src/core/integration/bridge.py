"""
Integration Bridge

Manages the coexistence of old and new architectures during the migration.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI

from src.core.adapters import (
    create_legacy_command_adapter,
    create_legacy_config_adapter,
    create_legacy_session_adapter,
)
from src.core.di.services import get_service_collection, set_service_provider
from src.core.interfaces.command_service import ICommandService
from src.core.interfaces.configuration import IConfig
from src.core.interfaces.di import IServiceProvider

logger = logging.getLogger(__name__)


class IntegrationBridge:
    """Manages the integration between old and new architectures."""
    
    def __init__(self, app: FastAPI):
        """Initialize the integration bridge.
        
        Args:
            app: The FastAPI application
        """
        self.app = app
        self.feature_flags = self._load_feature_flags()
        self.legacy_initialized = False
        self.new_initialized = False
    
    def _load_feature_flags(self) -> dict[str, bool]:
        """Load feature flags from environment variables.
        
        Returns:
            Dictionary of feature flags
        """
        return {
            "use_new_session_service": self._get_bool_env("USE_NEW_SESSION_SERVICE", False),
            "use_new_command_service": self._get_bool_env("USE_NEW_COMMAND_SERVICE", False),
            "use_new_backend_service": self._get_bool_env("USE_NEW_BACKEND_SERVICE", False),
            "use_new_request_processor": self._get_bool_env("USE_NEW_REQUEST_PROCESSOR", False),
            "enable_dual_mode": self._get_bool_env("ENABLE_DUAL_MODE", True),
        }
    
    def _get_bool_env(self, key: str, default: bool) -> bool:
        """Get a boolean environment variable.
        
        Args:
            key: Environment variable key
            default: Default value
            
        Returns:
            Boolean value
        """
        value = os.environ.get(key, "").lower()
        if value in ("true", "1", "yes", "on"):
            return True
        elif value in ("false", "0", "no", "off"):
            return False
        return default
    
    async def initialize_legacy_architecture(self) -> None:
        """Initialize the legacy architecture."""
        if self.legacy_initialized:
            return
        
        logger.info("Initializing legacy architecture")
        
        # Initialize legacy components as they were before
        # This will be called from the existing main.py lifespan
        
        self.legacy_initialized = True
        logger.info("Legacy architecture initialized")
    
    async def initialize_new_architecture(self) -> None:
        """Initialize the new SOLID architecture."""
        if self.new_initialized:
            return
        
        logger.info("Initializing new SOLID architecture")
        
        # Get service collection
        services = get_service_collection()
        
        # Register adapters that bridge legacy and new systems
        self._register_bridge_services(services)
        
        # Build and set service provider
        provider = services.build_service_provider()
        set_service_provider(provider)
        
        # Store provider in app state
        self.app.state.service_provider = provider
        
        self.new_initialized = True
        logger.info("New SOLID architecture initialized")
    
    def _register_bridge_services(self, services) -> None:
        """Register bridge services that connect old and new architectures.
        
        Args:
            services: The service collection
        """
        # Register config adapter
        if hasattr(self.app.state, 'config'):
            config_adapter = create_legacy_config_adapter(self.app.state.config)
            services.add_instance(IConfig, config_adapter)
        
        # Register command service adapter if legacy command parser exists
        if hasattr(self.app.state, 'command_parser'):
            command_adapter = create_legacy_command_adapter(self.app.state.command_parser)
            services.add_instance(ICommandService, command_adapter)
    
    def get_service_provider(self) -> IServiceProvider | None:
        """Get the service provider if new architecture is initialized.
        
        Returns:
            Service provider or None
        """
        if self.new_initialized:
            return getattr(self.app.state, 'service_provider', None)
        return None
    
    def should_use_new_service(self, service_name: str) -> bool:
        """Check if we should use the new implementation of a service.
        
        Args:
            service_name: Name of the service
            
        Returns:
            True if new service should be used
        """
        flag_key = f"use_new_{service_name}"
        return self.feature_flags.get(flag_key, False)
    
    def is_dual_mode_enabled(self) -> bool:
        """Check if dual mode is enabled.
        
        Returns:
            True if dual mode is enabled
        """
        return self.feature_flags.get("enable_dual_mode", True)
    
    async def cleanup(self) -> None:
        """Cleanup both architectures."""
        logger.info("Cleaning up integration bridge")
        
        # Cleanup will be handled by individual lifespan managers
        
        self.legacy_initialized = False
        self.new_initialized = False


# Global bridge instance
_bridge: IntegrationBridge | None = None


def get_integration_bridge(app: FastAPI | None = None) -> IntegrationBridge:
    """Get the global integration bridge.
    
    Args:
        app: FastAPI application (required for first call)
        
    Returns:
        The integration bridge
    """
    global _bridge
    if _bridge is None:
        if app is None:
            raise ValueError("FastAPI app required for first call to get_integration_bridge")
        _bridge = IntegrationBridge(app)
    return _bridge


def set_integration_bridge(bridge: IntegrationBridge) -> None:
    """Set the global integration bridge.
    
    Args:
        bridge: The integration bridge to set
    """
    global _bridge
    _bridge = bridge