"""Provider lifecycle management and post-build hooks.

This module manages the global service provider state and handles post-build
initialization hooks, separate from pure registration logic.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Generator
from contextlib import contextmanager

from src.core.interfaces.di_interface import IServiceProvider

# Global provider state
_service_provider: IServiceProvider | None = None
# Lock for thread-safe provider access and temporary provider contexts
_provider_lock = threading.RLock()

logger = logging.getLogger(__name__)


def _get_di_diagnostics() -> bool:
    """Get DI diagnostics setting from environment."""
    return os.getenv("DI_STRICT_DIAGNOSTICS", "false").lower() in (
        "true",
        "1",
        "yes",
    )


def get_or_build_service_provider() -> IServiceProvider:
    """Get the global service provider or build one if it doesn't exist.

    This function requires that get_service_collection() is available from
    src.core.di.services to avoid circular imports.

    Returns:
        The global service provider
    """
    global _service_provider
    # Backward-compatibility: keep the legacy `src.core.di.services._service_provider`
    # variable in sync with the canonical provider lifecycle state. Some tests
    # reset the provider by assigning to the legacy variable directly.
    try:
        from src.core.di import services as di_services

        if hasattr(di_services, "_service_provider"):
            legacy_provider = di_services._service_provider  # type: ignore[attr-defined]
            if legacy_provider is None:
                _service_provider = None
            else:
                # Type checker doesn't know the type from hasattr/getattr, so cast is needed
                _service_provider = legacy_provider  # type: ignore[assignment]
    except (ImportError, AttributeError) as e:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Failed to sync with legacy _service_provider: %s", e, exc_info=True
            )
    if _service_provider is None:
        # Import here to avoid circular import
        from src.core.di.services import get_service_collection, register_core_services

        services = get_service_collection()
        # Ensure baseline registrations exist when building a global provider directly.
        # This keeps lazy provider construction backward-compatible while allowing
        # staged app startup to start from an empty collection and register once.
        register_core_services(services, None)
        if _get_di_diagnostics():
            di_logger = logging.getLogger("llm.di")
            if di_logger.isEnabledFor(logging.INFO):
                di_logger.info(
                    "Building service provider; descriptors=%d",
                    len(services._descriptors),  # type: ignore[attr-defined]
                )
        _service_provider = services.build_service_provider()
        # Register feature parity tracking after provider is built
        post_build_hooks(_service_provider)
        try:
            from src.core.di import services as di_services

            di_services._service_provider = _service_provider  # type: ignore[attr-defined]
        except (ImportError, AttributeError) as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to sync legacy _service_provider after build: %s",
                    e,
                    exc_info=True,
                )
    return _service_provider


def set_service_provider(provider: IServiceProvider | None) -> None:
    """Set the global service provider (used for tests/late init).

    Args:
        provider: The ServiceProvider instance to set as the global provider, or None to reset
    """
    global _service_provider
    with _provider_lock:
        _service_provider = provider
        try:
            from src.core.di import services as di_services

            di_services._service_provider = provider  # type: ignore[attr-defined]
        except (ImportError, AttributeError) as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to sync legacy _service_provider in set_service_provider: %s",
                    e,
                    exc_info=True,
                )


def get_service_provider() -> IServiceProvider:
    """Return the global service provider, building it if necessary.

    This function returns the provider as-is without any self-healing behavior.
    Missing services will fail fast with ServiceResolutionError.

    Returns:
        The global service provider
    """
    return get_or_build_service_provider()


def get_current_service_provider() -> IServiceProvider:
    """Get the currently installed service provider without building implicitly.

    This is a fail-fast accessor that returns the currently installed provider
    or raises an exception if none is installed. It does NOT call
    get_or_build_service_provider() to avoid implicit provider builds.

    Returns:
        The currently installed service provider

    Raises:
        RuntimeError: If no service provider is currently installed
    """
    with _provider_lock:
        if _service_provider is None:
            raise RuntimeError("No service provider is currently installed")
        return _service_provider


@contextmanager
def temporary_service_provider(
    provider: IServiceProvider,
) -> Generator[None, None, None]:
    """Context manager to temporarily install a service provider.

    This context manager stores the previous provider, sets the new provider
    for the duration of the context, and always restores the previous provider
    even if exceptions occur. It is safe for nested usage within a single thread
    (uses a re-entrant lock).

    The context manager also keeps the legacy `src.core.di.services._service_provider`
    in sync exactly like `set_service_provider` does.

    Args:
        provider: The service provider to temporarily install

    Yields:
        None - the provider is installed for the duration of the context

    Example:
        ```python
        with temporary_service_provider(validation_provider):
            # Use validation_provider here
            current = get_current_service_provider()
            assert current is validation_provider
        # Previous provider is restored
        ```
    """
    global _service_provider

    with _provider_lock:
        # Store previous provider
        previous_provider = _service_provider

        # Set new provider
        _service_provider = provider

        # Sync with legacy provider
        try:
            from src.core.di import services as di_services

            di_services._service_provider = provider  # type: ignore[attr-defined]
        except (ImportError, AttributeError) as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to sync legacy _service_provider in temporary_service_provider: %s",
                    e,
                    exc_info=True,
                )

    try:
        yield
    finally:
        with _provider_lock:
            # Always restore previous provider
            _service_provider = previous_provider

            # Sync with legacy provider
            try:
                from src.core.di import services as di_services

                di_services._service_provider = previous_provider  # type: ignore[attr-defined]
            except (ImportError, AttributeError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to sync legacy _service_provider when restoring: %s",
                        e,
                        exc_info=True,
                    )


def post_build_hooks(provider: IServiceProvider) -> None:
    """Execute post-build hooks after provider is built.

    This includes feature parity registry initialization and other
    post-build setup that should happen once after the provider is built.

    Args:
        provider: The service provider that was just built
    """
    from src.core.di.registration_helpers.post_build_actions import (
        initialize_feature_parity_registry,
        register_tool_call_handlers,
    )

    initialize_feature_parity_registry(provider)
    register_tool_call_handlers(provider)
