import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.connectors.base import LLMBackend


class BackendRegistry:
    """A registry for dynamically discovering and managing LLM backend factories.

    RACE CONDITION FIX: Added thread-safe access to backend registry.
    """

    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., LLMBackend]] = {}

        # PHASE 4: Production hardening - enhanced lock with monitoring
        try:
            from src.core.services.production_concurrency_guard import (
                production_metrics,
            )

            self._lock = threading.Lock()
            self._has_production_monitoring = True
            self._production_metrics = production_metrics
        except ImportError:
            self._lock = threading.Lock()
            self._has_production_monitoring = False

    def register_backend(self, name: str, factory: Callable[..., "LLMBackend"]) -> None:
        """Registers a backend factory with the given name.

        Args:
            name: The unique name of the backend (e.g., "openai", "gemini").
            factory: A callable that can create an instance of LLMBackend.
        """
        if not name:
            raise ValueError("Backend name must be a non-empty string.")
        if not callable(factory):
            raise TypeError("Backend factory must be a callable.")

        # RACE CONDITION FIX + PHASE 4: Atomic backend registration with monitoring
        start_time = time.time()
        with self._lock:
            wait_time = time.time() - start_time
            if self._has_production_monitoring and wait_time > 0.1:
                self._production_metrics.record_lock_contention(
                    wait_time, "backend_registry"
                )

            if name in self._factories:
                if self._has_production_monitoring:
                    self._production_metrics.record_race_condition_warning(
                        f"duplicate_backend_registration:{name}"
                    )
                logging.warning(
                    f"Backend '{name}' is already registered. Skipping registration."
                )
                return
            self._factories[name] = factory

    def get_backend_factory(self, name: str) -> Callable[..., "LLMBackend"]:
        """Retrieves the factory for a registered backend.

        Args:
            name: The name of the backend.

        Returns:
            The callable factory for the specified backend.

        Raises:
            ValueError: If the backend name is not registered.
        """
        # RACE CONDITION FIX: Thread-safe factory access
        with self._lock:
            factory = self._factories.get(name)
            if not factory:
                # Enhanced error message for OAuth connectors in Multi User Mode (Requirement 6.5)
                error_msg = f"Backend '{name}' is not registered."

                # Check if this is an OAuth connector that was skipped in Multi User Mode
                try:
                    from src.core.common.backend_discovery_state import (
                        get_skipped_oauth_connectors,
                        is_extracted_backend_name,
                        is_running_in_multi_user_mode,
                        normalize_backend_name,
                    )

                    if is_running_in_multi_user_mode():
                        skipped = get_skipped_oauth_connectors()
                        normalized_name = normalize_backend_name(name)
                        explicitly_skipped = any(
                            normalized_name == connector.replace("_", "-")
                            for connector in skipped
                        )
                        oauth_like_name = is_extracted_backend_name(normalized_name)
                        if explicitly_skipped or oauth_like_name:
                            error_msg = (
                                f"Backend '{name}' is not available in Multi User Mode. "
                                f"OAuth-based connectors are blocked in production deployments to prevent "
                                f"use of personal credentials. Use --single-user-mode for local development, "
                                f"or configure a non-OAuth backend with static API keys."
                            )
                except ImportError:
                    # If connectors module not loaded yet, use generic message
                    pass

                raise ValueError(error_msg)
            return factory

    def get_registered_backends(self) -> list[str]:
        """Returns a list of names of all registered backends."""
        # RACE CONDITION FIX: Thread-safe backend list access
        with self._lock:
            return list(self._factories.keys())


# Global instance of the registry
backend_registry = BackendRegistry()
