"""
Base command implementation.

This module provides the base class for all commands in the new architecture.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod, abstractproperty
from collections.abc import Mapping
from typing import Any, final

from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session

logger = logging.getLogger(__name__)


class BaseCommand(ABC):
    """
    Base class for all commands in the new architecture.

    This class enforces that commands are created through the DI container
    by making the constructor protected and providing validation methods.

    To create a command instance, use the CommandFactory:

    ```python
    # Get the command factory from the DI container
    command_factory = service_provider.get_service(CommandFactory)

    # Create a command instance
    command = command_factory.create(MyCommand)
    ```
    """

    def __new__(cls, *args, **kwargs):
        """
        Control instantiation of command classes.

        This method is called before __init__ and can prevent direct instantiation
        outside of the DI container in non-test environments.

        Returns:
            A new instance of the command class

        Raises:
            RuntimeError: If attempting to directly instantiate a command class
                         outside of tests or DI container
        """
        # Allow instantiation in test environments
        import sys

        is_test_env = "pytest" in sys.modules or hasattr(sys, "_called_from_test")

        # Check if we're being called from the DI container
        import traceback

        stack = traceback.extract_stack()
        from_di = any("src/core/di/" in frame.filename for frame in stack)

        # Also allow instantiation from the command factory
        from_factory = any("command_factory.py" in frame.filename for frame in stack)

        # Allow direct instantiation in tests or from DI container/factory
        if is_test_env or from_di or from_factory or cls.__name__ == "BaseCommand":
            return super().__new__(cls)

        # Otherwise, raise an error
        raise RuntimeError(
            f"Direct instantiation of {cls.__name__} is not allowed. "
            f"Use the CommandFactory or DI container to create command instances."
        )

    @abstractproperty
    def name(self) -> str:
        """Command name."""

    @abstractproperty
    def format(self) -> str:
        """Command format string."""

    @abstractproperty
    def description(self) -> str:
        """Command description."""

    @property
    def examples(self) -> list[str]:
        """Command examples (optional)."""
        return []

    @abstractmethod
    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """
        Execute the command.

        Args:
            args: Command arguments
            session: The session
            context: Optional context

        Returns:
            The command result
        """

    @final
    def _validate_di_usage(self) -> None:
        """
        Validate that this command instance was created through proper DI.

        This method should be called by commands that require dependency injection
        to ensure they weren't instantiated directly without proper dependencies.

        Raises:
            RuntimeError: If the command was instantiated without proper DI
        """
        # Check if this command requires DI by examining its constructor
        import inspect

        # Get the constructor's class
        constructor_class = self.__class__

        # Check if the class has explicitly defined its own __init__ method
        # If it has an __init__ that is identical to BaseCommand.__init__, it doesn't need DI
        if (
            constructor_class.__init__ is BaseCommand.__init__
            or constructor_class.__init__.__qualname__.startswith(
                constructor_class.__name__
            )
        ):
            # This is likely a stateless command or one with an explicitly defined constructor
            # No validation needed
            return

        init_signature = inspect.signature(constructor_class.__init__)

        # If the constructor has parameters beyond 'self', it requires DI
        required_params = [
            name
            for name, param in init_signature.parameters.items()
            if name != "self" and param.default is inspect.Parameter.empty
        ]

        if required_params:
            # This command requires DI. Check if it was properly initialized
            # by verifying that required attributes are set
            missing_deps = []
            for param_name in required_params:
                # Convert parameter name to likely attribute name
                attr_name = f"_{param_name}"
                if not hasattr(self, attr_name) or getattr(self, attr_name) is None:
                    missing_deps.append(param_name)

            if missing_deps:
                raise RuntimeError(
                    f"Command {self.__class__.__name__} requires dependency injection "
                    f"but was instantiated without required dependencies: {missing_deps}. "
                    f"Use dependency injection container to create this command instead "
                    f"of direct instantiation."
                )
