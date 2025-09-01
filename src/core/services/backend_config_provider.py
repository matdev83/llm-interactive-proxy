from __future__ import annotations

from collections.abc import Iterable

from src.core.config.app_config import AppConfig, BackendConfig
from src.core.domain.chat import ChatRequest
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider
from src.core.services.backend_registry import backend_registry


class BackendConfigProvider(IBackendConfigProvider):
    """Adapter that exposes AppConfig.backends as a canonical provider.

    This ensures consumers receive `BackendConfig` objects regardless of
    whether the original config was a dict or a BackendSettings instance.
    """

    def __init__(self, app_config: AppConfig) -> None:
        self._app_config = app_config

    def get_backend_config(self, name: str) -> BackendConfig | None:
        """Return the BackendConfig for the given backend name or None."""
        # Try attribute access first (for BackendSettings)
        try:
            cfg = getattr(self._app_config.backends, name, None)
            if cfg is not None:
                if isinstance(cfg, BackendConfig):
                    # Return a copy to avoid modifying the original
                    return BackendConfig(**cfg.model_dump())
                elif isinstance(cfg, dict):
                    return BackendConfig(**cfg)
        except Exception as e:
            # Attribute probing may fail in test configurations; log at debug level
            import logging

            logging.getLogger(__name__).debug(
                "get_backend_config attribute access failed for %s: %s",
                name,
                e,
                exc_info=True,
            )

        # Fallback to dict-style access
        try:
            val = self._app_config.backends.get(name)
            if val is not None:
                if isinstance(val, BackendConfig):
                    # Return a copy to avoid modifying the original
                    return BackendConfig(**val.model_dump())
                elif isinstance(val, dict):
                    return BackendConfig(**val)
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug(
                "get_backend_config dict access failed for %s: %s",
                name,
                e,
                exc_info=True,
            )

        return None

    def iter_backend_names(self) -> Iterable[str]:
        """Iterate over known backend names."""
        # Include both registered backends and any backends explicitly configured
        registered = set(backend_registry.get_registered_backends())

        # Add any backends that are explicitly configured
        try:
            # Check if backends has __dict__ attribute (BackendSettings does)
            if hasattr(self._app_config.backends, "__dict__"):
                for key in self._app_config.backends.__dict__:
                    # Skip default_backend and non-backend attributes
                    if key != "default_backend" and not key.startswith("_"):
                        registered.add(key)
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug(
                "iter_backend_names failed while inspecting __dict__: %s",
                e,
                exc_info=True,
            )

        return registered

    def get_default_backend(self) -> str:
        """Return the configured default backend name."""
        try:
            default = self._app_config.backends.default_backend
            if default and isinstance(default, str):
                return default
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug(
                "get_default_backend failed to access default_backend: %s",
                e,
                exc_info=True,
            )
        return "openai"

    def get_functional_backends(self) -> set[str]:
        """Return a set of backend names that are considered functional (e.g. have API keys)."""
        try:
            # If backends has a functional_backends property, use it
            if hasattr(self._app_config.backends, "functional_backends"):
                backends = self._app_config.backends.functional_backends
                if isinstance(backends, set) and backends:  # Non-empty set
                    return backends
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug(
                "get_functional_backends failed reading property: %s", e, exc_info=True
            )

        # Build a set of backends with api_key present
        result = set()

        # First check backends in __dict__ (for test environments)
        if hasattr(self._app_config.backends, "__dict__"):
            for name, value in self._app_config.backends.__dict__.items():
                # Skip non-backend attributes
                if (
                    name == "default_backend"
                    or name.startswith("_")
                    or not isinstance(value, BackendConfig)
                ):
                    continue

                if value.api_key:  # Non-empty api_key list
                    result.add(name)

        # Then check backends via get_backend_config for any we missed
        for name in self.iter_backend_names():
            if name in result:
                continue  # Already processed

            cfg = self.get_backend_config(name)
            if cfg and cfg.api_key:
                result.add(name)

        return result

    def apply_backend_config(
        self, request: ChatRequest, backend_type: str, config: AppConfig
    ) -> ChatRequest:
        """Apply backend-specific configuration to a request.

        Args:
            request: The chat completion request
            backend_type: The backend type
            config: The application configuration

        Returns:
            The updated request with backend-specific configuration applied
        """
        # For now, return the request unchanged
        # This method can be extended to apply backend-specific configurations
        # similar to the BackendConfigService.apply_backend_config method
        return request

    # Alias for backward compatibility with the interface
    def functional_backends(self) -> set[str]:
        """Alias for get_functional_backends for backward compatibility."""
        return self.get_functional_backends()
