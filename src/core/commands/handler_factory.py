"""
Command handler factory.

This module provides functionality to create and register command handlers.
"""

from __future__ import annotations

import logging

from src.core.commands.handlers.command_handler import (
    BackendCommandHandler,
    HelpCommandHandler,
    ICommandHandler,
    ModelCommandHandler,
    ProjectCommandHandler,
    TemperatureCommandHandler,
)
from src.core.commands.handlers.failover_handlers import (
    CreateFailoverRouteHandler,
    DeleteFailoverRouteHandler,
    ListFailoverRoutesHandler,
    RouteAppendHandler,
    RouteClearHandler,
    RouteListHandler,
    RoutePrependHandler,
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
from src.core.commands.handlers.project_dir_handler import ProjectDirCommandHandler
from src.core.commands.handlers.pwd_handler import PwdCommandHandler
from src.core.commands.handlers.reasoning_handlers import (
    GeminiGenerationConfigHandler,
    ReasoningEffortHandler,
    ThinkingBudgetHandler,
)
from src.core.commands.handlers.set_handler import SetCommandHandler
from src.core.commands.handlers.unset_handler import UnsetCommandHandler
from src.core.services.command_service import CommandRegistry

logger = logging.getLogger(__name__)


class CommandHandlerFactory:
    """Factory for creating and registering command handlers."""
    
    def __init__(self):
        """Initialize the factory."""
        self._registry = CommandRegistry()
        self._handler_classes: dict[str, type[ICommandHandler]] = {}
        self._handlers: dict[str, ICommandHandler] = {}
        
        # Register built-in command handlers
        self.register_handler_class(BackendCommandHandler)
        self.register_handler_class(ModelCommandHandler)
        self.register_handler_class(TemperatureCommandHandler)
        self.register_handler_class(ProjectCommandHandler)
        self.register_handler_class(HelpCommandHandler)
        self.register_handler_class(HelloCommandHandler)
        self.register_handler_class(OneOffCommandHandler)
        self.register_handler_class(PwdCommandHandler)
        self.register_handler_class(ProjectDirCommandHandler)
        
        # Register unified set and unset command handlers
        set_handler = SetCommandHandler()
        self.register_handler_class(lambda: set_handler)
        self.register_handler_class(UnsetCommandHandler)
        
        # Register reasoning handlers
        reasoning_effort_handler = ReasoningEffortHandler()
        thinking_budget_handler = ThinkingBudgetHandler()
        gemini_config_handler = GeminiGenerationConfigHandler()
        self.register_handler_class(lambda: reasoning_effort_handler)
        self.register_handler_class(lambda: thinking_budget_handler)
        self.register_handler_class(lambda: gemini_config_handler)
        
        # Register specialized handlers with the set command handler
        set_handler.register_handler(reasoning_effort_handler)
        set_handler.register_handler(thinking_budget_handler)
        set_handler.register_handler(gemini_config_handler)
        
        # Register loop detection handlers
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
        
        # Register specialized handlers with the set command handler
        set_handler.register_handler(loop_detection_handler)
        set_handler.register_handler(tool_loop_detection_handler)
        set_handler.register_handler(tool_loop_max_repeats_handler)
        set_handler.register_handler(tool_loop_ttl_handler)
        set_handler.register_handler(tool_loop_mode_handler)
        
        # Register failover route command handlers
        self.register_handler_class(CreateFailoverRouteHandler)
        self.register_handler_class(DeleteFailoverRouteHandler)
        self.register_handler_class(ListFailoverRoutesHandler)
        self.register_handler_class(RouteAppendHandler)
        self.register_handler_class(RouteClearHandler)
        self.register_handler_class(RouteListHandler)
        self.register_handler_class(RoutePrependHandler)
    
    def register_handler_class(self, handler_class: type[ICommandHandler]) -> None:
        """Register a command handler class.
        
        Args:
            handler_class: The command handler class to register
        """
        # Create a temporary instance to get the name
        temp_instance = handler_class()
        name = temp_instance.name
        
        # Store the class for later instantiation
        self._handler_classes[name] = handler_class
        logger.debug(f"Registered command handler class: {name}")
    
    def create_handlers(self) -> list[ICommandHandler]:
        """Create instances of all registered command handlers.
        
        Returns:
            List of command handler instances
        """
        handlers = []
        
        # Special case for help command - needs the registry
        help_class = self._handler_classes.get("help")
        if help_class:
            help_handler = help_class()
            handlers.append(help_handler)
            self._handlers["help"] = help_handler
        
        # Create other handlers
        for name, handler_class in self._handler_classes.items():
            if name != "help":  # Skip help, already handled
                handler = handler_class()
                handlers.append(handler)
                self._handlers[name] = handler
        
        # Update help handler with registry if it exists
        help_handler = self._handlers.get("help")
        if help_handler:
            help_handler.set_registry(self._handlers)
        
        return handlers
    
    def register_with_registry(self, registry: CommandRegistry) -> None:
        """Register all handlers with a command registry.
        
        Args:
            registry: The command registry to register with
        """
        # Create handlers if not already created
        if not self._handlers:
            self.create_handlers()
        
        # Register each handler
        for _name, handler in self._handlers.items():
            registry.register(handler)
            
        logger.info(f"Registered {len(self._handlers)} command handlers with registry")


def register_command_handlers(registry: CommandRegistry) -> None:
    """Register all command handlers with a registry.
    
    Args:
        registry: The command registry to register with
    """
    factory = CommandHandlerFactory()
    factory.register_with_registry(registry)