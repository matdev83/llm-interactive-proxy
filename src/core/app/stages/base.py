"""
Base interface for initialization stages.

This module defines the contract that all initialization stages must implement.
Each stage is responsible for registering a specific set of services with the
dependency injection container.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection

logger = logging.getLogger(__name__)


class InitializationStage(ABC):
    """
    Base class for application initialization stages.

    Each stage is responsible for registering a specific set of services
    with the dependency injection container. Stages can declare dependencies
    on other stages, and the ApplicationBuilder will execute them in the
    correct order using topological sorting.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique name for this stage.

        Returns:
            The stage name, used for logging and dependency resolution
        """

    @abstractmethod
    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """
        Execute the initialization stage.

        This method should register all services that this stage is responsible
        for with the provided ServiceCollection. It should not assume that
        services from other stages are available yet.

        Args:
            services: The service collection to register services with
            config: The application configuration

        Raises:
            Exception: If service registration fails
        """

    def get_dependencies(self) -> list[str]:
        """
        Get the list of stage names that this stage depends on.

        The ApplicationBuilder will ensure that all dependency stages
        are executed before this stage.

        Returns:
            List of stage names this stage depends on
        """
        return []

    def get_description(self) -> str:
        """
        Get a human-readable description of what this stage does.

        Returns:
            Description of the stage's purpose
        """
        return f"Initialization stage: {self.name}"

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """
        Validate that this stage can be executed successfully.

        This method is called before execute() to check if all prerequisites
        are met. The default implementation always returns True.

        Args:
            services: The service collection
            config: The application configuration

        Returns:
            True if the stage can be executed, False otherwise
        """
        return True

    def __str__(self) -> str:
        """String representation of the stage."""
        return f"{self.__class__.__name__}(name='{self.name}')"

    def __repr__(self) -> str:
        """Detailed string representation of the stage."""
        deps = self.get_dependencies()
        deps_str = f", dependencies={deps}" if deps else ""
        return f"{self.__class__.__name__}(name='{self.name}'{deps_str})"
