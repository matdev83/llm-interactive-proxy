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
        self,
        backend_type: str | None,
        model: str,
        excluded_backends: set[str] | None = None,
    ) -> str | None:
        """Resolve the specific backend instance to use.

        Args:
            backend_type: The requested backend type (e.g. "openai", "openai.1", or None)
            model: The requested model name
            excluded_backends: Backend instance names that must be skipped (e.g., permanently disabled)

        Returns:
            The resolved backend instance name (e.g. "openai.1"), or None if resolution failed.

        Raises:
            RoutingError: If the requested routing method is disabled by policy.
        """
        excluded = excluded_backends or set()

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
            return None if backend_type in excluded else backend_type

        # Case 2: Generic backend requested (e.g. "openai")
        if backend_type:
            if self._routing_config.disable_backend_names:
                raise RoutingError(
                    message=f"Routing by backend name ('{backend_type}') is disabled by policy.",
                    details={"backend_type": backend_type, "model": model},
                )
            return self._resolve_generic_backend(backend_type, excluded)

        # Case 3: Only model provided, discover backend
        if self._routing_config.disable_model_names:
            raise RoutingError(
                message=f"Routing by model name only ('{model}') is disabled by policy.",
                details={"model": model},
            )
        return self._discover_backend_for_model(model, excluded)

    def _resolve_generic_backend(
        self, backend_type: str, excluded: set[str]
    ) -> str | None:
        """Resolve a generic backend type to a specific instance using Round Robin."""
        instances = [
            i
            for i in self._find_instances_for_backend(backend_type)
            if i not in excluded
        ]

        if not instances:
            # If no specific instances found, fall back to the generic name
            # This handles cases where only "openai" is configured without "openai.1"
            return None if backend_type in excluded else backend_type

        return self._select_instance(backend_type, instances, excluded)

    def _discover_backend_for_model(self, model: str, excluded: set[str]) -> str | None:
        """Find a backend that supports the given model."""
        candidates = []

        # Match both fully qualified vendor/model and plain model names.
        # Backend selection is NOT inferred from "/" (only ":" selects a backend);
        # however many configurations still list plain model names (e.g., "gpt-4")
        # while requests may use vendor-qualified identifiers (e.g., "openai/gpt-4").
        model_variants = {model}
        if "/" in model:
            # Use the portion after the vendor prefix for backwards-compatible matching.
            _, tail = model.split("/", 1)
            if tail:
                model_variants.add(tail)

        # Iterate all available backends
        # usage of _config_provider.iter_backend_names() is appropriate
        if hasattr(self._config_provider, "iter_backend_names"):
            for backend_name in self._config_provider.iter_backend_names():
                cfg = self._config_provider.get_backend_config(backend_name)
                models = getattr(cfg, "models", None) if cfg else None
                if (
                    cfg
                    and models
                    and any(variant in models for variant in model_variants)
                    and backend_name not in excluded
                ):
                    candidates.append(backend_name)

        if not candidates:
            return None

        # If multiple candidates, use Round Robin selection
        # We use a special key for model-based routing counters
        return self._select_instance(f"model:{model}", candidates, excluded)

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

    def _select_instance(
        self, key: str, instances: list[str], excluded: set[str] | None = None
    ) -> str:
        """Select an instance from the list using Round Robin."""
        if excluded:
            instances = [i for i in instances if i not in excluded]
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

    def find_alternative_instances(
        self,
        model: str,
        exclude: list[str],
    ) -> list[str]:
        """Find backend instances that can serve the given model.

        This method is used by the failure handling strategy to find
        alternative backend instances when one fails.

        Args:
            model: Fully qualified model name (e.g., "openai/gpt-4o" or "gpt-4o").
            exclude: List of backend instance names to exclude (already tried).

        Returns:
            List of backend instance names that can serve the model,
            sorted for consistent ordering.
        """
        excluded_set = set(exclude)
        candidates: list[str] = []

        # Parse model to extract backend type hint if present
        # Format could be "vendor/model" or just "model"
        backend_hint = None
        model_name = model
        if "/" in model:
            parts = model.split("/", 1)
            backend_hint = parts[0]
            model_name = parts[1]

        # Check if config provider supports iteration
        if not hasattr(self._config_provider, "iter_backend_names"):
            return []

        for backend_name in self._config_provider.iter_backend_names():
            if backend_name in excluded_set:
                continue

            cfg = self._config_provider.get_backend_config(backend_name)
            if not cfg:
                continue

            # Check if this backend provides the model
            # Match against both full model name and model_name portion
            models_list = getattr(cfg, "models", []) or []
            if model in models_list or model_name in models_list:
                candidates.append(backend_name)
                continue

            # If we have a backend hint, check if backend type matches
            if backend_hint:
                # Extract base type from instance name (e.g., "openai.1" -> "openai")
                base_type = (
                    backend_name.split(".")[0] if "." in backend_name else backend_name
                )
                if base_type == backend_hint:
                    # Backend type matches, might support the model
                    # Add it as a candidate (will be validated when actually used)
                    candidates.append(backend_name)

        # Sort for consistent ordering
        candidates.sort()

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Found %d alternative instances for model '%s' (excluding %s): %s",
                len(candidates),
                model,
                exclude,
                candidates,
            )

        return candidates
