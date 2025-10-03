import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.connectors.base import LLMBackend


class BackendRegistry:
    """A registry for dynamically discovering and managing LLM backend factories."""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., LLMBackend]] = {}

    def register_backend(self, name: str, factory: Callable[..., "LLMBackend"]) -> None:
        """Registers a backend factory with the given name.

        Args:
            name: The unique name of the backend (e.g., "openai", "gemini").
            factory: A callable that can create an instance of LLMBackend.
        """
        if not isinstance(name, str) or not name:
            raise ValueError("Backend name must be a non-empty string.")
        if not callable(factory):
            raise TypeError("Backend factory must be a callable.")
        if name in self._factories:
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
        factory = self._factories.get(name)
        if not factory:
            raise ValueError(f"Backend '{name}' is not registered.")
        return factory

    def get_registered_backends(self) -> list[str]:
        """Returns a list of names of all registered backends."""
        return list(self._factories.keys())


# Global instance of the registry
backend_registry = BackendRegistry()
