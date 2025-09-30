"""
Global registry for domain command classes.

This module provides a central registry for domain command classes that can be
used for auto-discovery. Command classes register themselves using the
register_domain_command() function.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.domain.commands.base_command import BaseCommand

logger = logging.getLogger(__name__)


class DomainCommandRegistry:
    """
    Registry for domain command classes.

    This registry stores command class factories that can be used to create
    command instances with proper dependency injection.
    """

    def __init__(self) -> None:
        """Initialize the domain command registry."""
        self._factories: dict[str, Callable[..., BaseCommand]] = {}

    def register_command(self, name: str, factory: Callable[..., BaseCommand]) -> None:
        """
        Register a command class factory.

        Args:
            name: The unique name of the command
            factory: A callable that creates command instances

        Raises:
            ValueError: If the command name is empty or already registered
            TypeError: If the factory is not callable
        """
        if not isinstance(name, str) or not name:
            raise ValueError("Command name must be a non-empty string.")
        if not callable(factory):
            raise TypeError("Command factory must be a callable.")
        if name in self._factories:
            raise ValueError(f"Command '{name}' is already registered.")

        self._factories[name] = factory
        logger.debug(f"Registered domain command: {name}")

    def get_command_factory(self, name: str) -> Callable[..., BaseCommand]:
        """
        Get a command factory by name.

        Args:
            name: The name of the command

        Returns:
            The command factory

        Raises:
            ValueError: If the command is not registered
        """
        factory = self._factories.get(name)
        if not factory:
            raise ValueError(f"Command '{name}' is not registered.")
        return factory

    def get_registered_commands(self) -> list[str]:
        """
        Get a list of all registered command names.

        Returns:
            List of command names
        """
        return list(self._factories.keys())

    def has_command(self, name: str) -> bool:
        """
        Check if a command is registered.

        Args:
            name: The name of the command

        Returns:
            True if the command is registered, False otherwise
        """
        return name in self._factories


# Global instance of the registry
domain_command_registry = DomainCommandRegistry()
