from __future__ import annotations

from collections.abc import Iterable
from typing import Any

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

        # If an instance name is provided (e.g. "openai.1"), fall back to the base
        # backend config when the instance is not explicitly configured.
        base_name: str | None = None
        if "." in name:
            base_name = name.split(".", 1)[0]
        name_for_fallback = base_name or name

        # Handle dash-to-underscore mapping for backend names
        attr_name = name.replace(
            "-", "_"
        )  # Convert dashes to underscores for attribute access
        dash_name = name.replace("_", "-")  # Convert underscores to dashes

        # List of all possible names to try
        possible_names = [name, attr_name, dash_name]
        if base_name:
            possible_names.extend(
                [
                    base_name,
                    base_name.replace("-", "_"),
                    base_name.replace("_", "-"),
                ]
            )
        # Remove duplicates while preserving order
        possible_names = list(dict.fromkeys(possible_names))

        found_configs: list[BackendConfig] = []

        lookup_method = getattr(self._app_config.backends, "lookup", None)
        for lookup_name in possible_names:
            cfg: BackendConfig | dict | None = None
            try:
                if callable(lookup_method):
                    cfg = lookup_method(lookup_name)  # type: ignore[assignment]
                else:
                    cfg = self._app_config.backends.get(lookup_name, None)  # type: ignore[arg-type]
            except (AttributeError, TypeError, KeyError):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to lookup backend config for name %s",
                        lookup_name,
                        exc_info=True,
                    )
                cfg = None

            if cfg is None:
                continue
            if isinstance(cfg, dict):
                found_configs.append(BackendConfig(**cfg))
            else:
                # BackendSettings.lookup returns BackendConfig; treat any non-dict as BackendConfig.
                found_configs.append(cfg)

        if found_configs:
            for cfg in found_configs:
                if cfg.api_key:
                    return BackendConfig(**cfg.model_dump())

            resolved = BackendConfig(**found_configs[0].model_dump())

            # Credential reuse fallbacks.
            # Some connectors are just protocol variants and should reuse the base backend's credentials
            # when not explicitly configured.
            if not resolved.api_key and name_for_fallback in {
                "openai-responses",
                "openai_responses",
            }:
                base = self.get_backend_config("openai")
                if base and base.api_key:
                    return BackendConfig(**base.model_dump())

            return resolved

        # No config found; return an empty BackendConfig for compatibility.
        # (Some call sites expect a BackendConfig object rather than None.)
        if name_for_fallback in {"openai-responses", "openai_responses"}:
            base = self.get_backend_config("openai")
            if base and base.api_key:
                return BackendConfig(**base.model_dump())

        return BackendConfig()

    def iter_backend_names(self) -> Iterable[str]:
        """Iterate over known backend names."""
        # Include both registered backends and any backends explicitly configured
        registered = set(backend_registry.get_registered_backends())

        backends_config: Any = self._app_config.backends

        # Add any backends that are explicitly configured.
        # BackendSettings is iterable but yields (key, value) tuples; dict yields string keys.
        try:
            for raw in backends_config:
                key: str | None = None
                if isinstance(raw, str):
                    key = raw
                elif isinstance(raw, tuple) and raw and isinstance(raw[0], str):
                    key = raw[0]

                if not key or key == "default_backend" or key.startswith("_"):
                    continue
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
            if default:
                return str(default)
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
                if backends:  # Non-empty set
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

                if value.api_key:  # Non-empty api_key
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
        # similar to the BackendConfigService.apply_backend_configmodel method
        return request

    # Alias for backward compatibility with the interface
    def functional_backends(self) -> set[str]:
        """Alias for get_functional_backends for backward compatibility."""
        return self.get_functional_backends()
