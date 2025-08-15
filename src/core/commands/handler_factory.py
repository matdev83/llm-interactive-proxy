from __future__ import annotations

import logging

from src.core.commands.handlers.backend_handlers import (
    BackendHandler,
    ModelHandler,
    OpenAIUrlHandler,
)
from src.core.commands.handlers.base_handler import ICommandHandler
from src.core.commands.handlers.loop_detection_handlers import (
    LoopDetectionHandler,
    ToolLoopDetectionHandler,
    ToolLoopMaxRepeatsHandler,
    ToolLoopModeHandler,
    ToolLoopTtlHandler,
)
from src.core.commands.handlers.reasoning_handlers import (
    ReasoningConfigHandler,
    ReasoningEffortHandler,
    TemperatureHandler,
    ThinkingBudgetHandler,
)

logger = logging.getLogger(__name__)


class CommandHandlerFactory:
    """Factory for creating command handlers.
    
    This factory creates and registers command handlers for all supported
    command parameters.
    """
    
    def __init__(self, functional_backends: set[str] | None = None):
        """Initialize the command handler factory.
        
        Args:
            functional_backends: Optional set of functional backends
        """
        self._handlers: dict[str, ICommandHandler] = {}
        self._functional_backends = functional_backends
        
        # Register default handlers
        self._register_default_handlers()
    
    def _register_default_handlers(self) -> None:
        """Register all default command handlers."""
        # Backend handlers
        self.register_handler(BackendHandler(self._functional_backends))
        self.register_handler(ModelHandler())
        self.register_handler(OpenAIUrlHandler())
        
        # Reasoning handlers
        self.register_handler(ReasoningEffortHandler())
        self.register_handler(ReasoningConfigHandler())
        self.register_handler(ThinkingBudgetHandler())
        self.register_handler(TemperatureHandler())
        
        # Loop detection handlers
        self.register_handler(LoopDetectionHandler())
        self.register_handler(ToolLoopDetectionHandler())
        self.register_handler(ToolLoopMaxRepeatsHandler())
        self.register_handler(ToolLoopTtlHandler())
        self.register_handler(ToolLoopModeHandler())
    
    def register_handler(self, handler: ICommandHandler) -> None:
        """Register a command handler.
        
        Args:
            handler: The handler to register
        """
        # Register by main name
        self._handlers[handler.name] = handler
        
        # Also register by aliases
        for alias in handler.aliases:
            self._handlers[alias] = handler
            
        logger.debug(f"Registered handler for '{handler.name}' and aliases: {handler.aliases}")
    
    def get_handler(self, param_name: str) -> ICommandHandler | None:
        """Get a handler for the given parameter name.
        
        Args:
            param_name: The parameter name
            
        Returns:
            The handler or None if no handler is registered
        """
        # Try exact match first
        if param_name in self._handlers:
            return self._handlers[param_name]
        
        # Normalize and try again
        normalized = param_name.lower().replace("_", "-")
        if normalized in self._handlers:
            return self._handlers[normalized]
        
        # Try slower iteration with can_handle
        for handler in self.get_all_handlers():
            if handler.can_handle(param_name):
                return handler
        
        return None
    
    def get_all_handlers(self) -> list[ICommandHandler]:
        """Get all registered handlers.
        
        Returns:
            List of all handlers (deduplicated)
        """
        unique_handlers = set()
        result = []
        
        for handler in self._handlers.values():
            if id(handler) not in unique_handlers:
                unique_handlers.add(id(handler))
                result.append(handler)
        
        return result
