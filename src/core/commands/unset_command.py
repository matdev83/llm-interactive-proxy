from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.commands.handler_factory import CommandHandlerFactory
from src.core.commands.handlers.base_handler import CommandHandlerResult
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session, SessionState
from src.core.interfaces.domain_entities_interface import ISessionState

logger = logging.getLogger(__name__)


class UnsetCommand(BaseCommand):
    """SOLID-based implementation of the unset command.

    This command uses individual handlers for each parameter, making it more
    maintainable and extensible than the original monolithic implementation.
    """

    name = "unset"
    format = "unset(key1, key2, ...)"
    description = "Unset previously configured options"
    examples = [
        "!/unset(model)",
        "!/unset(backend)",
        "!/unset(project)",
        "!/unset(model, project)",
        "!/unset(interactive)",
    ]

    def __init__(self) -> None:
        """Initialize the unset command."""
        self.handler_factory = CommandHandlerFactory()

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Execute the unset command with the given arguments.

        Args:
            args: The command arguments
            session: The session
            context: Optional context

        Returns:
            Result of the command execution
        """
        # Unset command can be called with positional args (e.g., unset(model, project))
        # or with key-value pairs where values are ignored (e.g., unset(model=1, project=1))
        # We need to extract the parameter names to unset

        params_to_unset = []

        # If args is a dict with numeric keys (positional args), extract values
        if all(
            isinstance(k, int) or k.isdigit() if isinstance(k, str) else False
            for k in args
        ):
            # Positional arguments
            params_to_unset = [str(v) for v in args.values()]
        else:
            # Named arguments - use the keys
            params_to_unset = list(args.keys())

        if not params_to_unset:
            return CommandResult(
                success=False,
                message="No parameters specified. Use unset(key1, key2, ...)",
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
        for param in params_to_unset:
            param_str = str(param).lower()

            # Find a handler for this parameter
            handler = None
            logger.debug(f"Looking for unset handler for parameter: {param_str}")

            # Try direct match first
            direct_match = False
            for h in handlers:
                if hasattr(h, "name") and h.name == param_str:
                    handler = h
                    direct_match = True
                    break

            # If no direct match, try can_handle
            if not direct_match:
                for h in handlers:
                    # Check if handler has can_handle method and it's callable
                    if hasattr(h, "can_handle") and callable(h.can_handle):
                        try:
                            can_handle_method = h.can_handle
                            if can_handle_method(param_str):
                                handler = h
                                break
                        except Exception as e:
                            logger.debug(
                                f"Error in can_handle for {getattr(h, 'name', 'unknown')}: {e}"
                            )

            if handler:
                # Handle the parameter - for unset, we pass None as the value
                # Check if handler has handle or execute method
                if hasattr(handler, "handle") and callable(handler.handle):
                    # For unset operations, we pass None to indicate removal
                    handle_method = handler.handle
                    handler_result = handle_method(None, current_state)
                elif hasattr(handler, "execute") and callable(handler.execute):
                    # Use execute method if handle is not available
                    import inspect

                    execute_method = handler.execute
                    if inspect.iscoroutinefunction(execute_method):
                        # We're already in an async context, so we can use await
                        # Pass None to indicate unset operation
                        handler_result = await execute_method({}, session)
                    else:
                        handler_result = execute_method({}, session)
                else:
                    handler_result = CommandHandlerResult(
                        success=False,
                        message=f"Handler {getattr(handler, 'name', 'unknown')} has no handle or execute method",
                        new_state=None,
                    )

                # Handle async results
                import inspect

                if inspect.isawaitable(handler_result):
                    handler_result = await handler_result

                # Get message from result
                message = getattr(handler_result, "message", str(handler_result))
                if message.strip():  # Only add non-empty messages
                    results.append(message)

                # Handle async results one more time
                import inspect

                if inspect.isawaitable(handler_result):
                    handler_result = await handler_result

                # Update the current state for subsequent handlers
                # Use getattr to safely access attributes
                new_state_attr = getattr(handler_result, "new_state", None)
                if new_state_attr is not None and new_state_attr is not None:
                    # Wrap the new state in SessionStateAdapter if it's a raw SessionState
                    from src.core.domain.session import SessionStateAdapter

                    new_state = handler_result.new_state
                    if isinstance(new_state, SessionState):
                        current_state = SessionStateAdapter(new_state)
                    elif isinstance(new_state, ISessionState):
                        current_state = new_state

                    # Also update the session state immediately
                    if current_state is not None:
                        session.state = current_state

                # Track overall success
                if not handler_result.success:
                    success = False
            else:
                # For unset, we have built-in fallbacks for common parameters
                # These are for parameters that don't have specific handlers yet
                if param_str in ("interactive", "interactive-mode"):
                    # Add None check for current_state
                    if current_state is not None:
                        new_backend_config = (
                            current_state.backend_config.with_interactive_mode(False)
                        )
                        new_state = current_state.with_backend_config(
                            new_backend_config
                        )
                        session.state = new_state
                        results.append("Interactive mode disabled")
                else:
                    # Unknown parameter - silently ignore for unset (common behavior)
                    logger.debug(f"Unknown unset parameter ignored: {param_str}")

        # Build the result message
        if results:
            non_empty_results = [r for r in results if r.strip()]
            if non_empty_results:
                result_message = "; ".join(non_empty_results)
            else:
                # All results were empty strings (silent operations)
                result_message = ""
        else:
            result_message = ""

        # Return the final state that was accumulated from all handlers
        # Only return new_state if it actually changed from the initial state
        return CommandResult(
            success=success,
            message=result_message,
            name=self.name,
            new_state=current_state if current_state != initial_state else None,
        )
