"""Backend lifecycle manager implementation.

Manages backend instance creation, caching, and shutdown.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, cast

from src.core.common.exceptions import BackendError
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)

if TYPE_CHECKING:
    from src.connectors.base import LLMBackend
    from src.core.interfaces.backend_config_provider_interface import (
        IBackendConfigProvider,
    )
    from src.core.interfaces.configuration_interface import IConfig
    from src.core.services.backend_factory import BackendFactory

logger = logging.getLogger(__name__)


class BackendLifecycleManager(IBackendLifecycleManager):
    """Service for managing backend lifecycle."""

    def __init__(
        self,
        factory: BackendFactory | None = None,
        config: IConfig | None = None,
        backend_config_provider: IBackendConfigProvider | None = None,
        per_session_limit: int = 32,
        global_backend_limit: int = 200,
    ) -> None:
        """Initialize the backend lifecycle manager.

        Args:
            factory: Factory for creating backends.
            config: Application configuration.
            backend_config_provider: Provider for backend configs.
            per_session_limit: Maximum number of per-session backends to cache.
            global_backend_limit: Maximum number of global backends to cache (default: 200).
        """
        self._factory = factory
        self._config = config
        self._backend_config_provider = backend_config_provider
        self._per_session_backend_limit = per_session_limit
        self._global_backend_limit = global_backend_limit

        # Backend caches - use OrderedDict for LRU eviction
        self._backends: OrderedDict[str, LLMBackend] = OrderedDict()
        self._per_session_backends: OrderedDict[str, LLMBackend] = OrderedDict()
        self._backend_configs: dict[str, Any] = {}

        # Disabled backends registry
        self._disabled_backends: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _is_per_session_cache_key(cache_key: str, backend_type: str) -> bool:
        """Return True when the cache key maps to a session-scoped backend."""
        return cache_key != backend_type

    async def get_or_create(
        self, backend_type: str, session_id: str | None = None
    ) -> LLMBackend:
        """Get existing backend or create new one.

        Cache key rules:
        - With session_id: `f"{backend_type}:{session_id}"`
        - Special case gemini-cli-acp without session_id: `f"{backend_type}:default"`
        - Otherwise: `backend_type`

        Per-session cache is LRU via OrderedDict; eviction shuts down backends.
        Permanently disabled backends raise BackendError.
        """
        if backend_type in self._disabled_backends:
            reason = self._disabled_backends[backend_type].get(
                "reason", "permanently disabled"
            )
            raise BackendError(
                message=f"Backend {backend_type} is permanently disabled: {reason}",
                backend_name=backend_type,
            )

        # Always use session-specific cache key if session_id is provided
        if session_id:
            cache_key = f"{backend_type}:{session_id}"
        elif backend_type == "gemini-cli-acp":
            # Special case for gemini-cli-acp which requires isolation
            cache_key = f"{backend_type}:default"
        else:
            cache_key = backend_type

        if self._is_per_session_cache_key(cache_key, backend_type):
            backend = self._per_session_backends.get(cache_key)
            if backend is not None:
                self._per_session_backends.move_to_end(cache_key)
                return backend
        else:
            backend = self._backends.get(cache_key)
            if backend is not None:
                # Move to end for LRU behavior
                self._backends.move_to_end(cache_key)
                return backend

        if not self._factory:
            raise BackendError(
                message=f"Cannot create backend {backend_type}: no factory configured",
                backend_name=backend_type,
            )

        try:
            from src.core.config.app_config import AppConfig, BackendConfig

            provider_backend_config: BackendConfig | None = None
            app_config: AppConfig = (
                cast(AppConfig, self._config) if self._config else AppConfig()
            )

            if self._backend_config_provider:
                provider_cfg = self._backend_config_provider.get_backend_config(
                    backend_type
                )

                if isinstance(provider_cfg, BackendConfig):
                    provider_backend_config = provider_cfg
                elif isinstance(provider_cfg, AppConfig):
                    app_config = provider_cfg

            if provider_backend_config is not None:
                try:
                    self._backend_configs[backend_type] = (
                        provider_backend_config.model_copy(deep=True)
                    )
                except AttributeError:
                    self._backend_configs[backend_type] = provider_backend_config
            else:
                self._backend_configs.pop(backend_type, None)

            created_backend: LLMBackend = await self._factory.ensure_backend(
                backend_type, app_config, provider_backend_config
            )
            if self._is_per_session_cache_key(cache_key, backend_type):
                self._per_session_backends[cache_key] = created_backend
                self._per_session_backends.move_to_end(cache_key)
                await self._enforce_per_session_backend_limit()
            else:
                self._backends[cache_key] = created_backend
                self._backends.move_to_end(cache_key)
                await self._enforce_global_backend_limit()
            return created_backend
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            raise BackendError(
                message=f"Failed to create backend {backend_type}: {e!s}",
                backend_name=backend_type,
            ) from e
        except Exception as e:
            raise BackendError(
                f"Failed to create backend '{backend_type}': {e}",
                backend_name=backend_type,
            ) from e

    async def shutdown(self, backend: LLMBackend) -> None:
        """Shutdown backend with proper cleanup."""
        shutdown_method = getattr(backend, "shutdown", None)
        if shutdown_method is None:
            return

        try:
            if inspect.iscoroutinefunction(shutdown_method):
                await shutdown_method()
            else:
                shutdown_method()
        except Exception:
            logger.exception("Error shutting down backend %s", backend.backend_type)

    def discard(self, backend_type: str, session_id: str | None, reason: str) -> None:
        """Discard and disable a backend instance.

        Disables globally and removes both global and per-session variants.
        Records the disablement reason.
        """
        # Record permanent disablement
        self._disabled_backends[backend_type] = {
            "reason": reason,
            "timestamp": time.time(),
        }

        global_cache_keys_to_remove = [backend_type]
        per_session_keys_to_remove = [
            key
            for key in list(self._per_session_backends)
            if key.startswith(f"{backend_type}:")
        ]

        def _unregister_and_shutdown(cache_key: str, backend: LLMBackend) -> None:
            with contextlib.suppress(Exception):
                if self._factory:
                    self._factory.unregister_backend_notifications(backend)
                    self._factory.unregister_backend(cache_key)
            task = asyncio.create_task(self.shutdown(backend))
            task.add_done_callback(lambda t: None)

        for cache_key in global_cache_keys_to_remove:
            backend = self._backends.pop(cache_key, None)
            if backend:
                _unregister_and_shutdown(cache_key, backend)
                if logger.isEnabledFor(logging.INFO):
                    logger.info("Discarded backend instance: %s", cache_key)

        for cache_key in per_session_keys_to_remove:
            backend = self._per_session_backends.pop(cache_key, None)
            if backend:
                _unregister_and_shutdown(cache_key, backend)
                if logger.isEnabledFor(logging.INFO):
                    logger.info("Discarded per-session backend instance: %s", cache_key)
                # Clean up backend config if this was the last instance of this backend type
                self._maybe_cleanup_backend_config(cache_key)

        # Clean up backend config for the discarded backend type if no instances remain
        if backend_type not in self._backends and not any(
            key.startswith(f"{backend_type}:") for key in self._per_session_backends
        ):
            self._backend_configs.pop(backend_type, None)

    def is_disabled(self, backend_type: str) -> bool:
        """Check if backend is permanently disabled."""
        return backend_type in self._disabled_backends

    def get_disabled_backends(self) -> dict[str, dict[str, Any]]:
        """Get the permanently disabled backend registry."""
        return dict(self._disabled_backends)

    def get_active_backends(self) -> dict[str, LLMBackend]:
        """Get all active backend instances."""
        # Merge global and per-session backends
        result: dict[str, LLMBackend] = dict(self._backends)
        result.update(self._per_session_backends)
        return result

    def _maybe_cleanup_backend_config(self, cache_key: str) -> None:
        """Clean up backend config if no instances of this backend type remain.

        Args:
            cache_key: The cache key that was evicted (e.g., "backend_type" or "backend_type:session_id")
        """
        # Extract backend_type from cache_key
        # Format is either "backend_type" or "backend_type:session_id"
        backend_type = cache_key.split(":", 1)[0]

        # Check if any instances of this backend type still exist
        has_global_instance = backend_type in self._backends
        has_per_session_instance = any(
            key.startswith(f"{backend_type}:") for key in self._per_session_backends
        )

        # Only clean up config if no instances remain
        if not has_global_instance and not has_per_session_instance:
            self._backend_configs.pop(backend_type, None)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Cleaned up backend config for %s (no instances remain)",
                    backend_type,
                )

    async def _enforce_per_session_backend_limit(self) -> None:
        """Ensure the per-session backend cache does not grow without bound."""
        limit = max(self._per_session_backend_limit, 1)
        while len(self._per_session_backends) > limit:
            evicted_key, evicted_backend = self._per_session_backends.popitem(
                last=False
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Evicting per-session backend %s due to cache limit %d",
                    evicted_key,
                    limit,
                )
            await self.shutdown(evicted_backend)
            # Clean up backend config if this was the last instance of this backend type
            self._maybe_cleanup_backend_config(evicted_key)

    async def _enforce_global_backend_limit(self) -> None:
        """Ensure the global backend cache does not grow without bound."""
        limit = max(self._global_backend_limit, 1)
        while len(self._backends) > limit:
            evicted_key, evicted_backend = self._backends.popitem(last=False)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Evicting global backend %s due to cache limit %d",
                    evicted_key,
                    limit,
                )
            await self.shutdown(evicted_backend)
            # Clean up backend config if this was the last instance of this backend type
            self._maybe_cleanup_backend_config(evicted_key)
