from __future__ import annotations

import logging
from threading import Lock

from src.core.common.exceptions import RoutingError
from src.core.config.app_config import RoutingConfig
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider

logger = logging.getLogger(__name__)


class BackendRoutingService:
    """Service for routing requests to appropriate backend instances.

    Handles:
    1. Variant 1: Explicit instance routing (e.g. "openai.1")
    2. Variant 2: Load balancing across instances (e.g. "openai" -> "openai.1", "openai.2")
    3. Variant 3: Model-based discovery (e.g. "gpt-4" -> "openai.1")
    """

    def __init__(
        self,
        config_provider: IBackendConfigProvider,
        routing_config: RoutingConfig | None = None,
    ) -> None:
        self._config_provider = config_provider
        self._routing_config = routing_config or RoutingConfig()
        self._rr_counters: dict[str, int] = {}
        self._rr_lock = Lock()

    def resolve_backend_instance(
        self, backend_type: str | None, model: str
    ) -> str | None:
        """Resolve the specific backend instance to use.

        Args:
            backend_type: The requested backend type (e.g. "openai", "openai.1", or None)
            model: The requested model name

        Returns:
            The resolved backend instance name (e.g. "openai.1"), or None if resolution failed.

        Raises:
            RoutingError: If the requested routing method is disabled by policy.
        """
        # Case 1: Specific instance requested (contains dot)
        if backend_type and "." in backend_type:
            if (
                self._routing_config.disable_backend_ids
                or self._routing_config.disable_backend_names
            ):
                raise RoutingError(
                    message=f"Routing by explicit backend instance ID ('{backend_type}') is disabled by policy.",
                    details={"backend_type": backend_type, "model": model},
                )
            return backend_type

        # Case 2: Generic backend requested (e.g. "openai")
        if backend_type:
            if self._routing_config.disable_backend_names:
                raise RoutingError(
                    message=f"Routing by backend name ('{backend_type}') is disabled by policy.",
                    details={"backend_type": backend_type, "model": model},
                )
            return self._resolve_generic_backend(backend_type)

        # Case 3: Only model provided, discover backend
        if self._routing_config.disable_model_names:
            raise RoutingError(
                message=f"Routing by model name only ('{model}') is disabled by policy.",
                details={"model": model},
            )
        return self._discover_backend_for_model(model)

    def _resolve_generic_backend(self, backend_type: str) -> str:
        """Resolve a generic backend type to a specific instance using Round Robin."""
        instances = self._find_instances_for_backend(backend_type)

        if not instances:
            # If no specific instances found, fall back to the generic name
            # This handles cases where only "openai" is configured without "openai.1"
            return backend_type

        return self._select_instance(backend_type, instances)

    def _discover_backend_for_model(self, model: str) -> str | None:
        """Find a backend that supports the given model."""
        candidates = []

        # Iterate all available backends
        # usage of _config_provider.iter_backend_names() is appropriate
        if hasattr(self._config_provider, "iter_backend_names"):
            for backend_name in self._config_provider.iter_backend_names():
                cfg = self._config_provider.get_backend_config(backend_name)
                if cfg and model in cfg.models:
                    candidates.append(backend_name)

        if not candidates:
            return None

        # If multiple candidates, use Round Robin selection
        # We use a special key for model-based routing counters
        return self._select_instance(f"model:{model}", candidates)

    def _find_instances_for_backend(self, backend_type: str) -> list[str]:
        """Find all configured instances for a given backend type."""
        instances = []

        if hasattr(self._config_provider, "iter_backend_names"):
            for name in self._config_provider.iter_backend_names():
                # Check if name is like "{backend_type}.{id}"
                if name.startswith(f"{backend_type}."):
                    instances.append(name)

        # Sort to ensure consistent order for Round Robin
        instances.sort()
        return instances

    def _select_instance(self, key: str, instances: list[str]) -> str:
        """Select an instance from the list using Round Robin."""
        if not instances:
            raise ValueError("No instances provided for selection")

        with self._rr_lock:
            current_index = self._rr_counters.get(key, 0)
            selected = instances[current_index % len(instances)]
            self._rr_counters[key] = current_index + 1

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Routing '{key}' to instance '{selected}' (RR index {current_index})"
            )

        return selected
