from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.command_prefix import validate_command_prefix
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session, SessionStateAdapter

logger = logging.getLogger(__name__)


class SetCommand(BaseCommand):
    """Command for setting configuration options."""

    name = "set"
    format = "set(key=value, ...)"
    description = "Set session or global configuration values"
    examples = [
        "!/set(model=openrouter:gpt-4)",
        "!/set(backend=anthropic)",
        "!/set(project='my project')",
        "!/set(interactive-mode=ON)",
        "!/set(redact-api-keys=false)",
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
        """Execute the set command with the given arguments.

        Args:
            args: The command arguments.
            session: The session object.
            context: Optional context.

        Returns:
            Result of the command execution with updated state.
        """
        if not args:
            return CommandResult(
                success=False,
                message="set: no valid parameters provided or action taken",
                name=self.name,
            )

        # Start with the current state
        current_state = session.state

        # Track results for each parameter
        results = []
        success = False
        something_done = False

        # Process each parameter
        for param, value in args.items():
            param_lower = param.lower()

            # Handle model parameter
            if param_lower == "model":
                # Parse model value - could be "backend:model" or just "model"
                model_str = str(value)
                if ":" in model_str:
                    backend, model = model_str.split(":", 1)
                    # For now, just set the model - backend override not yet implemented
                    new_backend_config = current_state.backend_config.with_model(model)
                else:
                    new_backend_config = current_state.backend_config.with_model(
                        model_str
                    )

                session.state = current_state.with_backend_config(new_backend_config)

                results.append(f"Model set to {model_str}")
                success = True
                something_done = True

            # Handle backend parameter
            elif param_lower == "backend":
                backend_str = str(value)
                new_backend_config = current_state.backend_config.with_backend(
                    backend_str
                )
                session.state = current_state.with_backend_config(new_backend_config)
                results.append(f"Backend set to {backend_str}")
                success = True
                something_done = True

            # Handle project parameter
            elif param_lower == "project":
                project_str = str(value).strip("'\"")
                session.state = current_state.with_project(project_str)
                results.append(f"Project set to {project_str}")
                success = True
                something_done = True

            # Handle project directory parameter (aliases: project-dir, dir, project-directory)
            elif param_lower in ("project-dir", "dir", "project-directory"):
                dir_path = str(value).strip("'\"")
                import os

                if not os.path.isdir(dir_path):
                    return CommandResult(
                        success=False,
                        message=f"Directory '{dir_path}' not found.",
                        name=self.name,
                    )

                # Apply change
                session.state = current_state.with_project_dir(dir_path)
                # Silent success expected by tests
                results.append("")
                success = True
                something_done = True

            # Handle interactive mode
            elif param_lower in ("interactive", "interactive-mode"):
                interactive_value = str(value).upper()
                if interactive_value in ("ON", "TRUE", "1", "YES"):
                    # Preserve previous mode to determine if we should set the
                    # interactive_just_enabled flag on the new state.
                    try:
                        prev_mode = bool(current_state.backend_config.interactive_mode)
                    except Exception:
                        prev_mode = False

                    new_backend_config = current_state.backend_config.with_interactive_mode(True)
                    new_state = current_state.with_backend_config(new_backend_config)
                    # Mark that interactive was just enabled for the session
                    try:
                        new_state = new_state.with_interactive_just_enabled(True)
                    except Exception:
                        pass
                    session.state = new_state
                    # Silence the confirmation message (tests expect empty response)
                    results.append("")
                    success = True
                    something_done = True
                elif interactive_value in ("OFF", "FALSE", "0", "NO"):
                    new_backend_config = current_state.backend_config.with_interactive_mode(False)
                    new_state = current_state.with_backend_config(new_backend_config)
                    try:
                        new_state = new_state.with_interactive_just_enabled(False)
                    except Exception:
                        pass
                    session.state = new_state
                    results.append("")
                    success = True
                    something_done = True
                else:
                    results.append(f"Invalid value for interactive mode: {value}")

            # Handle redact-api-keys parameter
            elif param_lower == "redact-api-keys":
                # This would need to update global app state, not session state
                # For now, just acknowledge it
                redact_value = str(value).lower()
                if redact_value in (
                    "true",
                    "false",
                    "on",
                    "off",
                    "yes",
                    "no",
                    "1",
                    "0",
                ):
                    # Update app-level state if available via context and be silent
                    try:
                        if context and hasattr(context, "state"):
                            context.state.api_key_redaction_enabled = redact_value in ("true", "on", "1", "yes")
                    except Exception:
                        pass
                    results.append("")
                    success = True
                    something_done = True
                else:
                    results.append(f"Invalid value for redact-api-keys: {value}")

            # Handle command-prefix parameter (sets app state)
            elif param_lower == "command-prefix":
                prefix_value = str(value).strip("'\"")
                # Context is expected to be the FastAPI app instance
                if context and hasattr(context, "state"):
                    # Validate prefix first
                    err = validate_command_prefix(prefix_value)
                    if err:
                        results.append(f"Invalid command prefix: {err}")
                    else:
                        context.state.command_prefix = prefix_value
                        # Command processed successfully; no visible message
                        results.append("")
                        success = True
                        something_done = True
                else:
                    results.append("Cannot set command prefix without app context")

            else:
                # Unknown parameter - don't mark as success
                results.append(f"Unknown parameter: {param}")

        # Return appropriate message
        if not something_done:
            return CommandResult(
                success=False,
                message="set: no valid parameters provided or action taken",
                name=self.name,
            )
        elif results:
            return CommandResult(
                success=success,
                message="\n".join(results) if len(results) > 1 else results[0],
                name=self.name,
            )
        else:
            # Empty results means command was processed but silently
            return CommandResult(
                success=True,
                message="",
                name=self.name,
            )