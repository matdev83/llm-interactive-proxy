"""
Command handler factory.

This module provides functionality to create and register command handlers.
"""

from __future__ import annotations

import logging
from typing import Any

# Legacy import for backward compatibility
from src.core.commands.handlers.command_handler import (
    ILegacyCommandHandler as ICommandHandler,
)
from src.core.commands.handlers.hello_handler import HelloCommandHandler
from src.core.commands.handlers.loop_detection_handlers import (
    LoopDetectionHandler,
    ToolLoopDetectionHandler,
    ToolLoopMaxRepeatsHandler,
    ToolLoopModeHandler,
    ToolLoopTTLHandler,
)
from src.core.commands.handlers.oneoff_handler import OneOffCommandHandler
from src.core.commands.handlers.openai_url_handler import OpenAIURLHandler
from src.core.commands.handlers.project_dir_handler import ProjectDirCommandHandler
from src.core.commands.handlers.project_handler import ProjectCommandHandler
from src.core.commands.handlers.pwd_handler import PwdCommandHandler
from src.core.commands.handlers.reasoning_handlers import (
    GeminiGenerationConfigHandler,
    ReasoningEffortHandler,
    ThinkingBudgetHandler,
)

# Import domain loop detection commands
from src.core.domain.commands.loop_detection_commands import (
    LoopDetectionCommand,
    ToolLoopDetectionCommand,
    ToolLoopMaxRepeatsCommand,
    ToolLoopModeCommand,
    ToolLoopTTLCommand,
)

# Import base command class
# Import domain commands that replace legacy handlers
from src.core.domain.commands.model_command import ModelCommand
from src.core.domain.commands.project_command import ProjectCommand
from src.core.domain.commands.temperature_command import TemperatureCommand
from src.core.domain.commands.set_command import SetCommand
from src.core.domain.commands.unset_command import UnsetCommand

# Import moved to local scope to avoid circular imports

logger = logging.getLogger(__name__)


class CommandHandlerFactory:
    """Factory for creating and registering command handlers."""

    def __init__(self) -> None:
        """Initialize the factory."""
        # Allow handler classes OR zero-arg callables returning handler instances

        # Handler can be a class or a callable factory
        self._handler_classes: dict[str, Any] = {}
        self._handlers: dict[str, ICommandHandler] = {}

        # Register domain commands that replace legacy handlers
        self.register_handler_class(ModelCommand)
        self.register_handler_class(ProjectCommand)
        self.register_handler_class(TemperatureCommand)
        self.register_handler_class(SetCommand)
        self.register_handler_class(UnsetCommand)

        # Import help command
        from src.core.domain.commands.help_command import HelpCommand

        self.register_handler_class(HelpCommand)

        # Legacy handlers that should be migrated to domain commands

        # TODO: Replace these with domain commands
        self.register_handler_class(HelloCommandHandler)
        self.register_handler_class(OneOffCommandHandler)
        self.register_handler_class(PwdCommandHandler)
        self.register_handler_class(ProjectDirCommandHandler)
        self.register_handler_class(OpenAIURLHandler)

        # Import domain reasoning commands
        # TODO: Create missing reasoning_commands module
        # from src.core.domain.commands.reasoning_commands import (
        #     GeminiGenerationConfigCommand,
        #     ReasoningEffortCommand,
        #     ThinkingBudgetCommand,
        # )

        # Register domain reasoning commands (commented out until modules are created)
        # self.register_handler_class(ReasoningEffortCommand)
        # self.register_handler_class(ThinkingBudgetCommand)
        # self.register_handler_class(GeminiGenerationConfigCommand)

        # Legacy reasoning handlers for backward compatibility
        reasoning_effort_handler = ReasoningEffortHandler()
        thinking_budget_handler = ThinkingBudgetHandler()
        gemini_config_handler = GeminiGenerationConfigHandler()

        # Legacy parameter handlers
        openai_url_handler = OpenAIURLHandler()
        project_dir_handler = ProjectDirCommandHandler()

        # Register legacy handlers - TODO: Replace with domain commands
        self.register_handler_class(lambda: reasoning_effort_handler)
        self.register_handler_class(lambda: thinking_budget_handler)
        self.register_handler_class(lambda: gemini_config_handler)
        self.register_handler_class(lambda: openai_url_handler)
        self.register_handler_class(lambda: project_dir_handler)

        # Register domain loop detection commands
        self.register_handler_class(LoopDetectionCommand)
        self.register_handler_class(ToolLoopDetectionCommand)
        self.register_handler_class(ToolLoopMaxRepeatsCommand)
        self.register_handler_class(ToolLoopTTLCommand)
        self.register_handler_class(ToolLoopModeCommand)

        # Legacy loop detection handlers for backward compatibility

        # Register legacy handlers - TODO: Remove when fully migrated
        loop_detection_handler = LoopDetectionHandler()
        tool_loop_detection_handler = ToolLoopDetectionHandler()
        tool_loop_max_repeats_handler = ToolLoopMaxRepeatsHandler()
        tool_loop_ttl_handler = ToolLoopTTLHandler()
        tool_loop_mode_handler = ToolLoopModeHandler()
        self.register_handler_class(lambda: loop_detection_handler)
        self.register_handler_class(lambda: tool_loop_detection_handler)
        self.register_handler_class(lambda: tool_loop_max_repeats_handler)
        self.register_handler_class(lambda: tool_loop_ttl_handler)
        self.register_handler_class(lambda: tool_loop_mode_handler)

        # Register failover route domain commands
        from src.core.domain.commands.failover_commands import (
            CreateFailoverRouteCommand,
            DeleteFailoverRouteCommand,
            ListFailoverRoutesCommand,
            RouteAppendCommand,
            RouteClearCommand,
            RouteListCommand,
            RoutePrependCommand,
        )

        self.register_handler_class(CreateFailoverRouteCommand)
        self.register_handler_class(DeleteFailoverRouteCommand)
        self.register_handler_class(ListFailoverRoutesCommand)
        self.register_handler_class(RouteAppendCommand)
        self.register_handler_class(RouteClearCommand)
        self.register_handler_class(RouteListCommand)
        self.register_handler_class(RoutePrependCommand)

    def register_handler_class(self, handler_class: Any) -> None:
        """Register a command handler class or factory.

        Args:
            handler_class: The command handler class or zero-arg factory to register
        """
        # Create a temporary instance to get the name
        instance = handler_class() if callable(handler_class) else handler_class
        name = instance.name

        # Store the class/factory for later instantiation
        self._handler_classes[name] = handler_class
        logger.debug(f"Registered command handler class: {name}")

    def create_handlers(self) -> list[ICommandHandler]:
        """Create instances of all registered command handlers.

        Returns:
            List of command handler instances
        """

        handlers: list[ICommandHandler] = []

        # Helper: instantiate
        def _make(hctor: Any) -> Any:
            return hctor() if callable(hctor) else hctor

        for name, handler_class_or_factory in self._handler_classes.items():
            try:
                handler = _make(handler_class_or_factory)
                handlers.append(handler)
                logger.debug(f"Created command handler: {name}")
            except Exception as e:
                logger.error(f"Failed to create command handler '{name}': {e}")

        return handlers

    def get_handler_by_name(self, name: str) -> ICommandHandler | None:
        """Get a specific handler by name.

        Args:
            name: The name of the handler

        Returns:
            The handler instance or None if not found
        """
        if name in self._handlers:
            return self._handlers[name]

        if name in self._handler_classes:
            handler_class_or_factory = self._handler_classes[name]
            try:
                handler = (
                    handler_class_or_factory()
                    if callable(handler_class_or_factory)
                    else handler_class_or_factory
                )
                # Type assertion to help mypy understand this is an ICommandHandler
                assert isinstance(handler, ICommandHandler)
                self._handlers[name] = handler
                return handler
            except Exception as e:
                logger.error(f"Failed to create command handler '{name}': {e}")

        return None

    def get_handler_names(self) -> list[str]:
        """Get the names of all registered handlers.

        Returns:
            List of handler names
        """
        return list(self._handler_classes.keys())
