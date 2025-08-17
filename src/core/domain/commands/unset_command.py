"""
Unset command for the SOLID architecture.

This module provides a command for unsetting configuration options.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, cast

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session, SessionStateAdapter
from src.constants import DEFAULT_COMMAND_PREFIX

logger = logging.getLogger(__name__)


class UnsetCommand(BaseCommand):
    """Command for unsetting configuration options."""

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

    def can_handle(self, command_name: str, args: Mapping[str, Any]) -> bool:
        """Check if this command can handle the given command name and arguments.

        Args:
            command_name: The name of the command.
            args: The command arguments.

        Returns:
            True if this command can handle the request.
        """
        return command_name.lower() == self.name

    async def execute(
        self,
        args: Mapping[str, Any],
        session: Session,
        context: Any = None,
    ) -> CommandResult:
        """Execute the unset command with the given arguments.

        Args:
            args: The command arguments.
            session_state: The session state adapter.
            context: Optional context.

        Returns:
            Result of the command execution.
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
                message="unset: nothing to do",
                name=self.name,
            )

        # Get the current state
        current_state = session.state

        # Track results for each parameter
        results = []
        something_done = False

        # Process each parameter
        for param in params_to_unset:
            param_lower = str(param).lower()

            # Handle model parameter
            if param_lower == "model":
                new_backend_config = current_state.backend_config.with_model(None)
                new_state = current_state.with_backend_config(new_backend_config)
                session.state = new_state # Update the session.state reference
                results.append("Model unset")
                something_done = True

            # Handle backend parameter
            elif param_lower == "backend":
                new_backend_config = current_state.backend_config.without_override()
                new_state = current_state.with_backend_config(new_backend_config)
                session.state = new_state # Update the session.state reference
                results.append("Backend unset")
                something_done = True

            # Handle project parameter
            elif param_lower == "project":
                new_state = session.state.with_project(None)
                session.state = new_state
                results.append("Project unset")
                something_done = True

            # Handle interactive mode
            elif param_lower in ("interactive", "interactive-mode"):
                new_backend_config = current_state.backend_config.with_interactive_mode(False)
                new_state = current_state.with_backend_config(new_backend_config)
                session.state = new_state # Update the session.state reference
                results.append("Interactive mode disabled")
                something_done = True

            # Handle command-prefix (reset to default in app state)
            elif param_lower == "command-prefix":
                if context and hasattr(context, "state"):
                    context.state.command_prefix = DEFAULT_COMMAND_PREFIX
                    # Indicate that something was done; unset returns empty message on success
                    results.append("")
                    something_done = True
                else:
                    # Cannot unset without app context
                    pass

            else:
                # Unknown parameter - silently ignore for unset
                # This matches the expected behavior from tests
                pass

        # Return appropriate message
        if not something_done:
            return CommandResult(
                success=False,
                message="unset: nothing to do",
                name=self.name,
            )
        elif results:
            # For unset, we typically return empty message on success
            return CommandResult(
                success=True,
                message="",  # Empty message for successful unset
                name=self.name,
            )
        else:
            # No results but something was done
            return CommandResult(
                success=True,
                message="",
                name=self.name,
            )
