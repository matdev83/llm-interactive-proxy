"""
Unset command implementation.

This module provides a domain command for unsetting (clearing) various session parameters.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, cast

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.configuration.reasoning_config import ReasoningConfiguration
from src.core.domain.session import Session, SessionState, SessionStateAdapter
from src.core.interfaces.domain_entities_interface import ISessionState

logger = logging.getLogger(__name__)


class UnsetCommand(BaseCommand):
    """Command for unsetting (clearing) various session parameters."""

    name = "unset"
    format = "unset(parameter)"
    description = "Unset (clear) various parameters for the session"
    examples = [
        "!/unset(backend)",
        "!/unset(model)",
        "!/unset(temperature)",
        "!/unset(interactive-mode)",
    ]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Unset various session parameters.

        Args:
            args: Command arguments with parameter name(s) to unset
            session: Current session
            context: Additional context data

        Returns:
            CommandResult indicating success or failure
        """
        # Handle case where no parameters are provided or args is empty
        if not args or all(not v for v in args.values()):
            return CommandResult(
                success=False,
                message="Parameter to unset must be specified",
                name=self.name,
            )

        # Process all parameters provided in args (keys with values or value=True)
        # In practice, we support both formats: unset(backend) and unset(backend=true)
        parameters_to_unset = []
        for param, value in args.items():
            if value:  # Value could be True or any non-empty string
                parameters_to_unset.append(param)

        if not parameters_to_unset:
            return CommandResult(
                success=False,
                message="Parameter to unset must be specified",
                name=self.name,
            )

        updated_state = session.state
        messages = []
        data: dict[str, Any] = {}

        for param in parameters_to_unset:
            # Accept legacy alias 'interactive' for 'interactive-mode'
            if param == "interactive":
                param = "interactive-mode"
            # Handle backend parameter
            if param == "backend":
                # Clear backend override via BackendConfiguration helper
                try:
                    new_backend_config = updated_state.backend_config.without_override()
                    updated_state = updated_state.with_backend_config(
                        new_backend_config
                    )
                except Exception:
                    # Fallback to attribute-level update
                    updated_state = self._update_session_state(
                        updated_state, "override_backend", None
                    )
                messages.append("Backend reset to default")
                data["backend"] = None

            # Handle model parameter
            elif param == "model":
                # Clear model override via BackendConfiguration helper
                try:
                    new_backend_config = updated_state.backend_config.with_model(None)
                    updated_state = updated_state.with_backend_config(
                        new_backend_config
                    )
                except Exception:
                    updated_state = self._update_session_state(
                        updated_state, "override_model", None
                    )
                messages.append("Model reset to default")
                data["model"] = None

            # Handle temperature parameter
            elif param == "temperature":
                # Get default temperature from reasoning config default
                default_config = ReasoningConfiguration()
                default_temp = default_config.temperature

                # Create new reasoning config with default temperature
                reasoning_config = session.state.reasoning_config.with_temperature(
                    default_temp
                )
                concrete_reasoning_config = cast(
                    ReasoningConfiguration, reasoning_config
                )

                # Update session state with new reasoning config
                updated_state = self._update_session_state_reasoning_config(
                    updated_state, concrete_reasoning_config
                )

                messages.append(f"Temperature reset to default ({default_temp})")
                data["temperature"] = default_temp

            # Handle interactive-mode parameter
            elif param == "interactive-mode":
                # Reset interactive mode in backend_config
                try:
                    new_backend_config = (
                        updated_state.backend_config.with_interactive_mode(True)
                    )
                    updated_state = updated_state.with_backend_config(
                        new_backend_config
                    )
                    # Also clear interactive_just_enabled flag
                    updated_state = updated_state.with_interactive_just_enabled(False)
                except Exception:
                    updated_state = self._update_session_state(
                        updated_state, "interactive_mode", True
                    )
                messages.append("Interactive mode reset to default (enabled)")
                data["interactive-mode"] = True

            # Handle redact-api-keys-in-prompts parameter
            elif param == "redact-api-keys-in-prompts":
                app = context.get("app")
                if app:
                    app.state.api_key_redaction_enabled = True
                messages.append("API key redaction reset to default (enabled)")
                data["redact-api-keys-in-prompts"] = True

            # Handle command-prefix parameter
            elif param == "command-prefix":
                app = context.get("app")
                if app:
                    app.state.command_prefix = "!/"
                messages.append("Command prefix reset to default (!/)")
                data["command-prefix"] = "!/"  # type: ignore

            elif param == "project":
                # Clear project
                try:
                    updated_state = updated_state.with_project(None)
                except Exception:
                    updated_state = self._update_session_state(
                        updated_state, "project", None
                    )
                messages.append("Project reset to default")
                data["project"] = None

            else:
                messages.append(f"Unknown parameter: {param}")

        # If all parameters were unknown, return failure
        if all("Unknown parameter" in msg for msg in messages):
            return CommandResult(
                success=False,
                message="unset: nothing to do",
                name=self.name,
            )

        # Return success with all parameter reset messages
        return CommandResult(
            success=True,
            message="\n".join(messages),
            name=self.name,
            data=data,
            new_state=updated_state,
        )

    def _update_session_state(
        self, state: ISessionState, attr_name: str, value: Any
    ) -> ISessionState:
        """Update session state with new attribute value."""
        if isinstance(state, SessionStateAdapter):
            # Working with SessionStateAdapter - get the underlying state
            old_state = state._state
            # Create copy with updated attribute
            new_state_dict = old_state.__dict__.copy()
            new_state_dict[attr_name] = value
            # Create new instance with updated values
            new_state = type(old_state)(**new_state_dict)
            return SessionStateAdapter(new_state)
        elif isinstance(state, SessionState):
            # Working with SessionState directly
            new_state_dict = state.__dict__.copy()
            new_state_dict[attr_name] = value
            new_state = type(state)(**new_state_dict)
            return SessionStateAdapter(new_state)
        else:
            # Fallback for other implementations
            # Try to set attribute directly if supported
            try:
                setattr(state, attr_name, value)
            except (AttributeError, TypeError):
                logger.warning(
                    f"Could not set {attr_name} on session state of type {type(state)}"
                )
            return state

    def _update_session_state_reasoning_config(
        self, state: ISessionState, reasoning_config: ReasoningConfiguration
    ) -> ISessionState:
        """Update session state with new reasoning config."""
        if isinstance(state, SessionStateAdapter):
            # Working with SessionStateAdapter - get the underlying state
            old_state = state._state
            new_state = old_state.with_reasoning_config(reasoning_config)
            return SessionStateAdapter(new_state)
        elif isinstance(state, SessionState):
            # Working with SessionState directly
            new_state = state.with_reasoning_config(reasoning_config)
            return SessionStateAdapter(new_state)
        else:
            # Fallback for other implementations
            logger.warning(
                f"Could not set reasoning_config on session state of type {type(state)}"
            )
            return state
