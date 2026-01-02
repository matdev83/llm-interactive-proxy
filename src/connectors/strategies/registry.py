"""Registry for backend initialization strategies."""

from __future__ import annotations

import logging
import threading
from typing import Any, cast

from src.core.common.exceptions import LLMProxyError
from src.core.interfaces.backend_initialization_strategy_interface import (
    IBackendInitializationStrategy,
)

logger = logging.getLogger(__name__)


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
                exc_type_llm: type[LLMProxyError] = cast(type[LLMProxyError], type(e))  # pyright: ignore[reportUnnecessaryCast]
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

    def __init__(self) -> None:
        """Initialize the registry."""
        self._strategies: dict[str, IBackendInitializationStrategy] = {}
        self._lock = threading.Lock()
        self._default_strategy = DefaultInitializationStrategy()
        self._logger = logger

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

        Args:
            connector_type: The connector type identifier.

        Returns:
            The initialization strategy for the connector type, or the default
            strategy if none is registered. Custom strategies are wrapped to
            add exception context.
        """
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
initialization_strategy_registry = InitializationStrategyRegistry()
