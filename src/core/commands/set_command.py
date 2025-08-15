from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI

from src.commands.base import BaseCommand, CommandResult
from src.core.commands.handler_factory import CommandHandlerFactory
from src.core.domain.session import SessionState

logger = logging.getLogger(__name__)


class SetCommandRefactored(BaseCommand):
    """Refactored implementation of the set command.
    
    This command uses individual handlers for each parameter, making it more
    maintainable and extensible than the original monolithic SetCommand.
    """
    
    name = "set"
    format = "set(key=value, ...)"
    description = "Set session or global configuration values"
    examples = [
        "!/set(model=openrouter:gpt-4)",
        "!/set(interactive=true)",
        "!/set(reasoning-effort=high)",
    ]
    
    def __init__(
        self, app: FastAPI | None = None, functional_backends: set[str] | None = None
    ) -> None:
        """Initialize the set command.
        
        Args:
            app: The FastAPI application
            functional_backends: Optional set of functional backends
        """
        super().__init__(app, functional_backends)
        self.handler_factory = CommandHandlerFactory(functional_backends)
    
    def execute(
        self, args: Mapping[str, Any], state: Any, app: dict[str, Any] | None = None
    ) -> CommandResult:
        """Execute the set command with the given arguments.
        
        Args:
            args: The command arguments
            state: The current session state (ProxyState)
            app: Optional application state
            
        Returns:
            Result of the command execution
        """
        if not args:
            return CommandResult(
                self.name, False, "No parameters specified. Use set(key=value, ...)"
            )
        
        # For backward compatibility, create a SessionState from the ProxyState
        current_state = self._create_session_state_from_proxy_state(state)
        
        # Track results for each parameter
        results = []
        success = True
        
        # Process each parameter
        for param, value in args.items():
            handler = self.handler_factory.get_handler(param)
            if handler:
                # Handle the parameter
                handler_result = handler.handle(value, current_state)
                results.append(handler_result.message)
                
                # Update the current state for subsequent handlers
                if handler_result.new_state:
                    current_state = handler_result.new_state
                
                # Track overall success
                if not handler_result.success:
                    success = False
            else:
                # No handler found for this parameter
                results.append(f"Unknown parameter: {param}")
                success = False
        
        # Apply the state changes to the legacy ProxyState
        if success:
            self._apply_session_state_to_proxy_state(current_state, state)
        
        # Build the result message
        result_message = "\n".join(results)
        return CommandResult(self.name, success, result_message)
    
    def _create_session_state_from_proxy_state(self, proxy_state: Any) -> SessionState:
        """Create a SessionState from a legacy ProxyState.
        
        Args:
            proxy_state: The legacy ProxyState
            
        Returns:
            A new SessionState
        """
        # Import here to avoid circular imports
        from src.core.domain.configuration.backend_config import BackendConfiguration
        from src.core.domain.configuration.loop_detection_config import (
            LoopDetectionConfiguration,
        )
        from src.core.domain.configuration.reasoning_config import (
            ReasoningConfiguration,
        )
        
        # This is a temporary adapter function - in the future, we'd use SessionState directly
        return SessionState(
            backend_config=BackendConfiguration(
                backend_type=proxy_state.override_backend,
                model=proxy_state.override_model,
                api_url=None,
                interactive_mode=proxy_state.interactive_mode,
                failover_routes=proxy_state.failover_routes,
                oneoff_backend=proxy_state.oneoff_backend,
                oneoff_model=proxy_state.oneoff_model,
                invalid_override=proxy_state.invalid_override,
                openai_url=proxy_state.openai_url,
            ),
            reasoning_config=ReasoningConfiguration(
                reasoning_effort=proxy_state.reasoning_effort,
                thinking_budget=proxy_state.thinking_budget,
                temperature=proxy_state.temperature,
                reasoning_config=proxy_state.reasoning_config,
                gemini_generation_config=proxy_state.gemini_generation_config,
            ),
            loop_config=LoopDetectionConfiguration(
                loop_detection_enabled=proxy_state.loop_detection_enabled
                if proxy_state.loop_detection_enabled is not None else True,
                tool_loop_detection_enabled=proxy_state.tool_loop_detection_enabled
                if proxy_state.tool_loop_detection_enabled is not None else True,
                tool_loop_max_repeats=proxy_state.tool_loop_max_repeats,
                tool_loop_ttl_seconds=proxy_state.tool_loop_ttl_seconds,
                tool_loop_mode=proxy_state.tool_loop_mode,
            ),
            project=proxy_state.project,
            project_dir=proxy_state.project_dir,
            interactive_just_enabled=proxy_state.interactive_just_enabled,
            hello_requested=proxy_state.hello_requested,
            is_cline_agent=proxy_state.is_cline_agent,
        )
    
    def _apply_session_state_to_proxy_state(self, session_state: SessionState, proxy_state: Any) -> None:
        """Apply SessionState changes to a legacy ProxyState.
        
        Args:
            session_state: The new SessionState
            proxy_state: The legacy ProxyState to update
        """
        # Backend configuration
        proxy_state.override_backend = session_state.backend_config.backend_type  # type: ignore
        proxy_state.override_model = session_state.backend_config.model  # type: ignore
        proxy_state.oneoff_backend = session_state.backend_config.oneoff_backend  # type: ignore
        proxy_state.oneoff_model = session_state.backend_config.oneoff_model  # type: ignore
        proxy_state.invalid_override = session_state.backend_config.invalid_override  # type: ignore
        proxy_state.interactive_mode = session_state.backend_config.interactive_mode  # type: ignore
        proxy_state.failover_routes = session_state.backend_config.failover_routes  # type: ignore
        proxy_state.openai_url = session_state.backend_config.openai_url  # type: ignore
        
        # Reasoning configuration
        proxy_state.reasoning_effort = session_state.reasoning_config.reasoning_effort  # type: ignore
        proxy_state.thinking_budget = session_state.reasoning_config.thinking_budget  # type: ignore
        proxy_state.temperature = session_state.reasoning_config.temperature  # type: ignore
        proxy_state.reasoning_config = session_state.reasoning_config.reasoning_config  # type: ignore
        proxy_state.gemini_generation_config = session_state.reasoning_config.gemini_generation_config  # type: ignore
        
        # Loop detection configuration
        proxy_state.loop_detection_enabled = session_state.loop_config.loop_detection_enabled  # type: ignore
        proxy_state.tool_loop_detection_enabled = session_state.loop_config.tool_loop_detection_enabled  # type: ignore
        proxy_state.tool_loop_max_repeats = session_state.loop_config.tool_loop_max_repeats  # type: ignore
        proxy_state.tool_loop_ttl_seconds = session_state.loop_config.tool_loop_ttl_seconds  # type: ignore
        proxy_state.tool_loop_mode = session_state.loop_config.tool_loop_mode  # type: ignore
        
        # Project and other settings
        proxy_state.project = session_state.project
        proxy_state.project_dir = session_state.project_dir
        proxy_state.interactive_just_enabled = session_state.interactive_just_enabled
        proxy_state.hello_requested = session_state.hello_requested
        proxy_state.is_cline_agent = session_state.is_cline_agent
