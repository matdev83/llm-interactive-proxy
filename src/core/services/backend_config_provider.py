from __future__ import annotations

from collections.abc import Iterable, Mapping

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
        import logging

        logger = logging.getLogger(__name__)
        logger.debug(f"get_backend_config called for name: {name}")

        # Handle dash-to-underscore mapping for backend names
        attr_name = name.replace(
            "-", "_"
        )  # Convert dashes to underscores for attribute access
        dash_name = name.replace("_", "-")  # Convert underscores to dashes

        # List of all possible names to try
        possible_names = [name, attr_name, dash_name]
        # Remove duplicates while preserving order
        possible_names = list(dict.fromkeys(possible_names))

        logger.debug(f"Trying backend config lookup for names: {possible_names}")

        # Collect all found configurations
        found_configs = []

        for lookup_name in possible_names:
            # Try attribute access
            try:
                cfg = getattr(self._app_config.backends, lookup_name, None)
                logger.debug(f"getattr(backends, '{lookup_name}'): {cfg}")
                if cfg is not None and isinstance(cfg, BackendConfig):
                    found_configs.append((lookup_name, cfg, "attribute"))
                    logger.debug(
                        f"Found config via attribute '{lookup_name}': api_key={cfg.api_key}"
                    )
                elif cfg is not None:
                    logger.debug(
                        f"Found non-BackendConfig via attribute '{lookup_name}': {type(cfg)} = {cfg}"
                    )
            except Exception as e:
                logger.debug(f"Exception in getattr(backends, '{lookup_name}'): {e}")

            # Try dict-style access
            try:
                cfg = self._app_config.backends.get(lookup_name)
                if cfg is not None and isinstance(cfg, BackendConfig | dict):
                    if isinstance(cfg, dict):
                        cfg = BackendConfig(**cfg)
                    found_configs.append((lookup_name, cfg, "dict"))
                    logger.debug(
                        f"Found config via dict '{lookup_name}': api_key={cfg.api_key}"
                    )
            except Exception:
                pass

            # Try direct __dict__ access
            try:
                if hasattr(self._app_config.backends, "__dict__"):
                    backends_dict = self._app_config.backends.__dict__
                    cfg = backends_dict.get(lookup_name)
                    if cfg is not None and isinstance(cfg, BackendConfig):
                        found_configs.append((lookup_name, cfg, "__dict__"))
                        logger.debug(
                            f"Found config via __dict__ '{lookup_name}': api_key={cfg.api_key}"
                        )
            except Exception:
                pass

        # If we found multiple configs, prefer the one with a non-empty API key
        if found_configs:
            logger.debug(
                f"Found {len(found_configs)} configurations: {[(n, c.api_key, m) for n, c, m in found_configs]}"
            )

            # First, try to find one with a non-empty API key
            for lookup_name, cfg, method in found_configs:
                if cfg.api_key:  # Non-empty api_key list
                    logger.debug(
                        f"Using config from '{lookup_name}' ({method}) with non-empty api_key: {cfg.api_key}"
                    )
                    return BackendConfig(**cfg.model_dump())

            # If no config has an API key, return the first one
            lookup_name, cfg, method = found_configs[0]
            logger.debug(
                f"Using first config from '{lookup_name}' ({method}) with empty api_key"
            )
            return BackendConfig(**cfg.model_dump())

        logger.debug(f"No backend config found for any of: {possible_names}")
        return None

    def iter_backend_names(self) -> Iterable[str]:
        """Iterate over known backend names."""
        # Include both registered backends and any backends explicitly configured
        registered = set(backend_registry.get_registered_backends())

        backends_config = self._app_config.backends

        # Add any backends that are explicitly configured
        try:
            # Handle dictionary-style configurations (e.g. when loading from YAML)
            if isinstance(backends_config, Mapping):
                for key in backends_config.keys():
                    if isinstance(key, str) and key != "default_backend":
                        registered.add(key)

            # Check if backends has __dict__ attribute (BackendSettings does)
            elif hasattr(backends_config, "__dict__"):
                for key in backends_config.__dict__:
                    # Skip default_backend and non-backend attributes
                    if key != "default_backend" and not key.startswith("_"):
                        registered.add(key)
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug(
                "iter_backend_names failed while inspecting backend configuration: %s",
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
