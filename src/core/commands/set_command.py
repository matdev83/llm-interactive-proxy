from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.commands.handler_factory import CommandHandlerFactory
from src.core.commands.handlers.base_handler import CommandHandlerResult
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session, SessionState

logger = logging.getLogger(__name__)


class SetCommand(BaseCommand):
    """SOLID-based implementation of the set command.

    This command uses individual handlers for each parameter, making it more
    maintainable and extensible than the original monolithic implementation.
    """

    name = "set"
    format = "set(key=value, ...)"
    description = "Set session or global configuration values"
    examples = [
        "!/set(model=openrouter:gpt-4)",
        "!/set(interactive=true)",
        "!/set(reasoning-effort=high)",
    ]

    def __init__(self) -> None:
        """Initialize the set command."""
        self.handler_factory = CommandHandlerFactory()

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Execute the set command with the given arguments.

        Args:
            args: The command arguments
            session: The session
            context: Optional context

        Returns:
            Result of the command execution
        """
        if not args:
            return CommandResult(
                success=False,
                message="No parameters specified. Use set(key=value, ...)",
                name=self.name,
            )

        # Get the current state from the session
        # Keep a reference to the initial state to check if it changed
        initial_state = session.state
        current_state = session.state

        # Track results for each parameter
        results = []
        success = True

        # Create handlers
        handlers = self.handler_factory.create_handlers()

        # Process each parameter
        for param, value in args.items():
            # Find a handler for this parameter
            handler = None
            logger.debug(f"Looking for handler for parameter: {param}")
            # Try direct match first
            direct_match = False
            for h in handlers:
                if hasattr(h, "name") and h.name == param:
                    handler = h
                    direct_match = True
                    logger.debug(
                        f"Direct match found for {param}: {getattr(h, 'name', 'unknown')}"
                    )
                    break

            # If no direct match, try can_handle
            if not direct_match:
                for h in handlers:
                    logger.debug(f"Checking handler: {getattr(h, 'name', 'unknown')}")
                    if hasattr(h, "can_handle") and callable(h.can_handle):
                        try:
                            can_handle_result = h.can_handle(param)
                            logger.debug(
                                f"Handler {getattr(h, 'name', 'unknown')}.can_handle({param}) = {can_handle_result}"
                            )
                            if can_handle_result:
                                handler = h
                                logger.debug(
                                    f"Found handler for {param}: {getattr(h, 'name', 'unknown')}"
                                )
                                break
                        except Exception as e:
                            logger.debug(
                                f"Error in can_handle for {getattr(h, 'name', 'unknown')}: {e}"
                            )

            if handler:
                # Handle the parameter
                # Check if handler has handle or execute method
                if hasattr(handler, "handle") and callable(handler.handle):
                    handler_result = handler.handle(value, current_state)  # type: ignore
                elif hasattr(handler, "execute") and callable(handler.execute):
                    # Use execute method if handle is not available
                    import inspect

                    # Domain BaseCommand implementations expect a Mapping of
                    # arguments (e.g., {"name": <val>}). Legacy handlers
                    # expect the raw value. Detect BaseCommand and adapt.
                    # Detect BaseCommand type safely; avoid UnboundLocalError if import fails
                    base_command = None
                    try:
                        from src.core.domain.commands.base_command import (
                            BaseCommand as _BaseCommand,
                        )

                        base_command = _BaseCommand
                    except Exception:
                        base_command = None  # type: ignore

                    exec_arg = value
                    if base_command is not None and isinstance(handler, base_command):
                        # Provide a mapping with both 'name' and 'value' for
                        # maximum compatibility during migration.
                        exec_arg = {"name": value, "value": value}

                    if inspect.iscoroutinefunction(handler.execute):
                        # We're already in an async context, so we can await
                        handler_result = await handler.execute(exec_arg, session)
                    else:
                        handler_result = handler.execute(exec_arg, session)
                else:
                    handler_result = CommandHandlerResult(
                        success=False,
                        message=f"Handler {getattr(handler, 'name', 'unknown')} has no handle or execute method",
                        new_state=None,
                    )

                # Get message from result
                message = getattr(handler_result, "message", str(handler_result))
                results.append(message)

                # Update the current state for subsequent handlers
                if hasattr(handler_result, "new_state") and handler_result.new_state:
                    # Wrap the new state in SessionStateAdapter if it's a raw SessionState
                    from src.core.domain.session import SessionStateAdapter

                    new_state = handler_result.new_state
                    if isinstance(new_state, SessionState):
                        current_state = SessionStateAdapter(new_state)
                    else:
                        current_state = new_state

                    logger.debug(
                        f"Updated current_state with new state from handler: {handler_result.new_state}"
                    )
                    # Also update the session state immediately
                    session.state = current_state

                # Track overall success
                if not handler_result.success:
                    success = False
            else:
                # No handler found for this parameter
                results.append(f"Unknown parameter: {param}")
                success = False

        # State changes have already been applied to the session during handler execution
        # Return the new state so the command service can update the session properly

        # Build the result message
        result_message = "\n".join(results)
        # Return the final state that was accumulated from all handlers
        # Only return new_state if it actually changed from the initial state
        return CommandResult(
            success=success,
            message=result_message,
            name=self.name,
            new_state=current_state if current_state != initial_state else None,
        )

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
                failover_routes_data=proxy_state.failover_routes,
                oneoff_backend=proxy_state.oneoff_backend,
                oneoff_model=proxy_state.oneoff_model,
                invalid_override=proxy_state.invalid_override,
                openai_url=proxy_state.openai_url,
            ),
            # Interactive mode is part of backend_config in the new architecture
            reasoning_config=ReasoningConfiguration(
                reasoning_effort=proxy_state.reasoning_effort,
                thinking_budget=proxy_state.thinking_budget,
                temperature=proxy_state.temperature,
                reasoning_config=proxy_state.reasoning_config,
                gemini_generation_config=proxy_state.gemini_generation_config,
            ),
            loop_config=LoopDetectionConfiguration(
                loop_detection_enabled=(
                    proxy_state.loop_detection_enabled
                    if proxy_state.loop_detection_enabled is not None
                    else True
                ),
                tool_loop_detection_enabled=(
                    proxy_state.tool_loop_detection_enabled
                    if proxy_state.tool_loop_detection_enabled is not None
                    else True
                ),
                tool_loop_max_repeats=proxy_state.tool_loop_max_repeats,
                tool_loop_ttl_seconds=proxy_state.tool_loop_ttl_seconds,
                tool_loop_mode=proxy_state.tool_loop_mode,
            ),
            project=proxy_state.project,
            project_dir=proxy_state.project_dir,
        )

    def _apply_session_state_to_proxy_state(
        self, session_state: SessionState, proxy_state: Any
    ) -> None:
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
        proxy_state.interactive_mode = session_state.session.default_interactive_mode  # type: ignore
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


# Backwards-compatible alias expected by some tests
SetCommandRefactored = SetCommand

__all__ = ["SetCommand", "SetCommandRefactored"]
