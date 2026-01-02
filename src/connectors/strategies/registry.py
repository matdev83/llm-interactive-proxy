"""Registry for backend initialization strategies."""

from __future__ import annotations

import importlib
import logging
import pkgutil
import threading
from collections.abc import Callable
from typing import Any, cast

from src.core.common.exceptions import LLMProxyError
from src.core.interfaces.backend_initialization_strategy_interface import (
    IBackendInitializationStrategy,
)

logger = logging.getLogger(__name__)


def _auto_discover_strategies() -> None:
    """Auto-discover and import all strategy modules in this package.

    This function is called lazily on first access to get_strategy() to avoid
    circular import issues. It discovers and imports all strategy modules in
    the strategies package, which triggers their registration code.

    Excludes registry.py, __init__.py, and modules starting with _.

    Note: Strategy modules import initialization_strategy_registry at module level,
    so the registry must exist before this function imports them. This is ensured
    by lazy discovery - the registry is created before any strategy modules are imported.
    """
    package = __package__
    if package is None:
        return

    # Get the package path
    try:
        package_path = __import__(package, fromlist=[""]).__path__  # type: ignore[attr-defined]
    except (ImportError, AttributeError):
        return

    # Discover and import all modules in the strategies package
    for _importer, modname, _ispkg in pkgutil.iter_modules(package_path):
        # Skip registry.py, __init__.py, and private modules (starting with _)
        if modname in ("registry", "__init__") or modname.startswith("_"):
            continue

        # Import the module to trigger its registration code
        try:
            full_module_name = f"{package}.{modname}"
            importlib.import_module(full_module_name)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Auto-discovered and imported strategy module: {full_module_name}"
                )
        except Exception as e:
            # Log but don't fail - some modules might not be strategies
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Failed to import strategy module {modname}: {e}",
                    exc_info=True,
                )


class DefaultInitializationStrategy:
    """Default initialization strategy that passes configuration unmodified.

    This strategy is used when no custom strategy is registered for a connector type.
    It returns a copy of the input configuration without any modifications.
    """

    def augment_init_config(self, init_config: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of the initialization configuration unmodified.

        Args:
            init_config: The base initialization configuration dictionary.

        Returns:
            A copy of the input configuration dictionary.
        """
        return dict(init_config)


class _ExceptionWrappingStrategy:
    """Wrapper strategy that adds connector context to exceptions."""

    def __init__(
        self,
        strategy: IBackendInitializationStrategy,
        connector_type: str,
    ) -> None:
        """Initialize the wrapper.

        Args:
            strategy: The underlying strategy to wrap.
            connector_type: The connector type for exception context.
        """
        self._strategy = strategy
        self._connector_type = connector_type

    def augment_init_config(self, init_config: dict[str, Any]) -> dict[str, Any]:
        """Augment config and wrap exceptions with connector context.

        Args:
            init_config: The base initialization configuration dictionary.

        Returns:
            The augmented initialization configuration dictionary.

        Raises:
            Exception: Any exception raised by the underlying strategy, wrapped
                with connector context.
        """
        try:
            return self._strategy.augment_init_config(init_config)
        except Exception as e:
            # Wrap exception with connector context
            error_msg = (
                f"Initialization strategy for connector '{self._connector_type}' "
                f"failed: {e!s}"
            )
            # Preserve LLMProxyError subclasses (domain errors)
            if isinstance(e, LLMProxyError):
                # Create new instance with updated message, preserving details and attributes
                if e.details:
                    details: dict[str, Any] = cast(dict[str, Any], e.details).copy()
                    details["connector_type"] = self._connector_type
                else:
                    details = {"connector_type": self._connector_type}
                # Copy any additional attributes from the original exception (excluding
                # message, details, status_code which are handled by the exception class)
                kwargs: dict[str, Any] = {}
                for attr_name in dir(e):
                    if (
                        not attr_name.startswith("_")
                        and attr_name
                        not in ["message", "details", "status_code", "args"]
                        and not callable(getattr(e, attr_name))
                    ):
                        kwargs[attr_name] = getattr(e, attr_name)
                # Re-raise with updated message and details
                # Note: status_code is handled by the exception class itself (e.g., ConfigurationError sets status_code=400)
                # Type checker needs help understanding that type(e) is a subclass of LLMProxyError here
                exc_type_llm: type[LLMProxyError] = cast(
                    type[LLMProxyError], type(e)
                )  # pyright: ignore[reportUnnecessaryCast]
                raise exc_type_llm(error_msg, details=details, **kwargs) from e
            # Preserve common built-in exception types
            elif isinstance(e, ValueError | TypeError | KeyError):
                exc_type_builtin = type(e)
                raise exc_type_builtin(error_msg) from e
            # For other exceptions, wrap as RuntimeError
            else:
                raise RuntimeError(error_msg) from e


class InitializationStrategyRegistry:
    """Registry for backend initialization strategies.

    This registry allows registering and retrieving initialization strategies
    by connector type. If no custom strategy is registered, a default strategy
    that passes configuration unmodified is returned.

    The registry is thread-safe and supports concurrent registration and retrieval.
    Exceptions raised by strategies are wrapped with connector context.
    """

    def __init__(self, discovery_func: Callable[[], None] | None = None) -> None:
        """Initialize the registry.

        Args:
            discovery_func: Optional function to use for strategy discovery.
                If None, uses the default `_auto_discover_strategies()` function.
                This parameter is primarily for testing to allow injection of mock
                discovery functions.
        """
        self._strategies: dict[str, IBackendInitializationStrategy] = {}
        self._lock = threading.Lock()
        self._default_strategy = DefaultInitializationStrategy()
        self._logger = logger
        self._discovered = False  # Flag to track if auto-discovery has run
        self._discovery_event = (
            threading.Event()
        )  # Event to signal discovery completion
        self._discovery_func = discovery_func or _auto_discover_strategies

    def register_strategy(
        self, connector_type: str, strategy: IBackendInitializationStrategy | None
    ) -> None:
        """Register an initialization strategy for a connector type.

        Args:
            connector_type: The connector type identifier (e.g., "anthropic", "gemini").
            strategy: The initialization strategy to register. Must implement
                IBackendInitializationStrategy (checked at static analysis time).

        Raises:
            ValueError: If connector_type is empty or strategy is None.
        """
        if not connector_type:
            raise ValueError("Connector type must be a non-empty string.")
        if strategy is None:
            raise ValueError("Strategy cannot be None.")

        with self._lock:
            self._strategies[connector_type] = strategy

    def get_strategy(self, connector_type: str) -> IBackendInitializationStrategy:
        """Get the initialization strategy for a connector type.

        If no custom strategy is registered, returns the default strategy
        and logs a warning. Custom strategies are wrapped to add connector
        context to exceptions.

        Lazy auto-discovery: Strategies are auto-discovered on first access
        to avoid circular import issues during module import.

        Args:
            connector_type: The connector type identifier.

        Returns:
            The initialization strategy for the connector type, or the default
            strategy if none is registered. Custom strategies are wrapped to
            add exception context.
        """
        # Lazy auto-discovery on first access (thread-safe with event synchronization)
        if not self._discovered:
            should_discover = False
            with self._lock:
                # Double-check pattern to ensure discovery only happens once
                if not self._discovered:
                    should_discover = True
                    # Don't set _discovered here - wait until discovery actually completes
                    # The event synchronization ensures other threads wait properly

            if should_discover:
                # This thread performs discovery
                try:
                    # Call discovery outside the lock to avoid deadlock when modules register
                    # Strategy modules will call register_strategy() which needs the lock
                    self._discovery_func()
                    # Mark as discovered only after discovery completes successfully
                    # This ensures strategies are registered before other threads proceed
                    with self._lock:
                        self._discovered = True
                finally:
                    # Signal completion to waiting threads
                    # Set event even if discovery raised an exception to prevent infinite waits
                    self._discovery_event.set()
                    # Also set _discovered in finally to prevent infinite retries on exceptions
                    with self._lock:
                        if not self._discovered:
                            self._discovered = True
            else:
                # Another thread is discovering, wait for completion
                self._discovery_event.wait()
                # After waiting, ensure _discovered is set (it should be, but be defensive)
                with self._lock:
                    if not self._discovered:
                        self._discovered = True
        else:
            # Discovery flag is set, but we must ensure discovery actually completed
            # Wait for event to be set (in case discovery is still in progress)
            self._discovery_event.wait()

        # Now discovery is complete, safe to check strategies
        with self._lock:
            strategy = self._strategies.get(connector_type)

        if strategy is None:
            if self._logger.isEnabledFor(logging.WARNING):
                self._logger.warning(
                    f"No custom initialization strategy registered for connector "
                    f"'{connector_type}'. Using default strategy.",
                    extra={"connector_type": connector_type},
                )
            return self._default_strategy

        # Wrap custom strategies to add exception context
        return _ExceptionWrappingStrategy(strategy, connector_type)


# Global instance of the registry
# Auto-discovery is now lazy (triggered on first get_strategy() call) to avoid
# circular import issues. Strategy modules can safely import initialization_strategy_registry
# at module level since the registry exists before they are imported.
initialization_strategy_registry = InitializationStrategyRegistry()
