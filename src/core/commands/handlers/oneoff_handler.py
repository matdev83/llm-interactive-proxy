"""
OneOff command handler for the SOLID architecture.

This module provides a command handler for setting a one-time override
for the backend and model for the next request.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.commands.handlers.base_handler import (
    BaseCommandHandler,
    CommandHandlerResult,
)
from src.core.domain.command_context import CommandContext
from src.core.domain.configuration.session_state_builder import SessionStateBuilder
from src.core.domain.session import SessionStateAdapter
from src.core.interfaces.domain_entities import ISessionState
from src.models import parse_model_backend

logger = logging.getLogger(__name__)


class OneOffCommandHandler(BaseCommandHandler):
    """Handler for setting a one-time override for the backend and model."""

    def __init__(self) -> None:
        """Initialize the oneoff command handler."""
        super().__init__("oneoff")

    @property
    def aliases(self) -> list[str]:
        """Aliases for the parameter name."""
        return ["one-off"]

    @property
    def description(self) -> str:
        """Description of the command."""
        return (
            "Sets a one-time override for the backend and model for the next request."
        )

    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return [
            "!/oneoff(openrouter/gpt-4)",
            "!/one-off(gemini/gemini-pro)",
            "!/oneoff(anthropic:claude-3-opus)",
        ]

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """
        return param_name.lower() in [self.name, *self.aliases]

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle setting a one-time override for the backend and model.

        Args:
            param_value: The backend/model value to set
            current_state: The current session state
            context: Optional command context

        Returns:
            A result containing success/failure status and updated state
        """
        if not param_value:
            return CommandHandlerResult(
                success=False,
                message="oneoff command requires a backend/model argument.",
            )

        # Get the argument key
        arg_key = param_value
        if isinstance(param_value, dict):
            if not param_value:
                return CommandHandlerResult(
                    success=False,
                    message="oneoff command requires a backend/model argument.",
                )
            arg_key = next(iter(param_value.keys()))

        # Parse the backend and model
        backend, model = parse_model_backend(arg_key)
        backend = backend.strip()
        model = model.strip()

        # Check for invalid format (no separator found)
        if ":" not in arg_key and "/" not in arg_key:
            return CommandHandlerResult(
                success=False,
                message="Invalid format. Use backend/model or backend:model.",
            )

        # Check for empty backend or model
        if not backend or not model:
            return CommandHandlerResult(
                success=False, message="Backend and model cannot be empty."
            )

        # Create new state with oneoff route
        builder = SessionStateBuilder(current_state)
        new_state = SessionStateAdapter(builder.with_backend_config(
            current_state.backend_config.with_oneoff_route(backend, model)
        ).build())

        return CommandHandlerResult(
            success=True,
            message=f"One-off route set to {backend}/{model}.",
            new_state=new_state,
        )
