"""
Command factory for creating command instances through DI.

This module provides a factory for creating command instances that enforces
proper dependency injection usage.
"""

from __future__ import annotations

import logging
from typing import TypeVar, cast

from src.core.di.container import ServiceCollection, ServiceProvider
from src.core.domain.commands.base_command import BaseCommand
from src.core.interfaces.factory_interface import IFactory

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseCommand)


class CommandFactory(IFactory[BaseCommand]):
    """
    Factory for creating command instances through DI.

    This factory enforces that commands are created through the DI container,
    preventing direct instantiation of commands that require dependencies.
    """

    def __init__(self, service_provider: ServiceProvider) -> None:
        """
        Initialize the command factory.

        Args:
            service_provider: The DI service provider to use for resolving commands
        """
        self._service_provider = service_provider

    def create(self, command_type: type[T]) -> T:
        """
        Create a command instance through the DI container.

        This method ensures that commands are always created with their
        required dependencies injected properly.

        Args:
            command_type: The type of command to create

        Returns:
            An instance of the requested command type

        Raises:
            ValueError: If the command type is not registered in the DI container
            RuntimeError: If the command could not be created through DI
        """
        try:
            command = self._service_provider.get_service(command_type)
            if command is None:
                raise ValueError(
                    f"Command type {command_type.__name__} is not registered in the DI container"
                )
            return cast(T, command)
        except Exception as e:
            logger.error(f"Failed to create command {command_type.__name__}: {e}")
            raise RuntimeError(
                f"Command {command_type.__name__} must be created through DI. "
                f"Ensure it is registered in the DI container. Error: {e}"
            ) from e

    @staticmethod
    def register_factory(services: ServiceCollection) -> None:
        """
        Register the command factory in the DI container.

        Args:
            services: The service collection to register with
        """
        services.add_singleton_factory(
            CommandFactory,
            lambda provider: CommandFactory(provider),
        )
