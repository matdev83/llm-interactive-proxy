from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class CommandHandlerFactory:
    """Factory for creating command handlers.

    DEPRECATED: This factory is no longer used as all commands are now registered
    through the DI container and CommandRegistry. This class remains for backward
    compatibility but will be removed in a future version.
    """

    def create_handlers(self) -> list[Any]:
        """Create and return all available command handlers.

        DEPRECATED: This method is no longer used as all commands are now registered
        through the DI container and CommandRegistry.

        Returns:
            Empty list as all commands are now DI-based
        """
        # Import the CommandRegistry to get DI-registered commands

        # Log a deprecation warning
        import warnings

        warnings.warn(
            "CommandHandlerFactory.create_handlers() is deprecated. "
            "Use CommandRegistry.get_instance().get_all() instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        # Return an empty list as all commands are now DI-based
        return []
