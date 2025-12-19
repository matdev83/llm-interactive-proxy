"""IdentityResolver service for resolving identity configuration.

This service extracts identity resolution logic from HybridConnector to provide
focused, testable components for backend identity resolution.

Requirements satisfied:
- Req 9: Phase Executor Extraction (IdentityResolver is part of infrastructure)
"""

import contextlib
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from src.core.config.app_config import AppConfig
    from src.core.interfaces.configuration_interface import IAppIdentityConfig


class IdentityResolver:
    """Service for resolving identity configuration for backend calls.

    Preference order:
    1. Backend-specific identity provided via backend_config or AppConfig.backends
    2. Identity attached to the current request
    3. Global application identity
    """

    def __init__(self, config: "AppConfig") -> None:
        """Initialize IdentityResolver.

        Args:
            config: Application configuration
        """
        self.config = config

    def resolve(
        self,
        backend: str,
        request_identity: "IAppIdentityConfig | None",
        backend_config: Any = None,
    ) -> "IAppIdentityConfig | None":
        """Resolve identity configuration for backend calls.

        Args:
            backend: Backend name
            request_identity: Identity attached to the current request
            backend_config: Optional backend-specific configuration object

        Returns:
            Resolved identity configuration or None if no identity found
        """
        # Preference 1: Backend-specific identity from backend_config
        if backend_config is not None and getattr(backend_config, "identity", None):
            return cast("IAppIdentityConfig", backend_config.identity)

        # Preference 2: Backend-specific identity from AppConfig.backends
        backend_identity = None
        if hasattr(self.config, "backends"):
            with contextlib.suppress(AttributeError):
                backend_settings = getattr(self.config.backends, backend)
                backend_identity = getattr(backend_settings, "identity", None)
        if backend_identity is not None:
            return cast("IAppIdentityConfig", backend_identity)

        # Preference 3: Request identity
        if request_identity is not None:
            return request_identity

        # Preference 4: Global application identity
        return getattr(self.config, "identity", None)
