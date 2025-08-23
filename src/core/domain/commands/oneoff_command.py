"""
Oneoff command implementation.

This module provides the oneoff command, which sets a one-time override for the backend and model.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.secure_base_command import StatelessCommandBase
from src.core.domain.model_utils import parse_model_backend
from src.core.domain.session import Session

logger = logging.getLogger(__name__)


class OneoffCommand(StatelessCommandBase, BaseCommand):
    """Command to set a one-time override for the backend and model."""

    def __init__(self) -> None:
        """Initialize without state services."""
        StatelessCommandBase.__init__(self)

    @property
    def name(self) -> str:
        return "oneoff"

    @property
    def format(self) -> str:
        return "oneoff(backend/model)"

    @property
    def description(self) -> str:
        return (
            "Sets a one-time override for the backend and model for the next request."
        )

    @property
    def examples(self) -> list[str]:
        return ["!/oneoff(openrouter/gpt-4)", "!/one-off(gemini/gemini-pro)"]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """
        Execute the oneoff command.

        Args:
            args: Command arguments
            session: The session
            context: Optional context

        Returns:
            The command result
        """
        if not args:
            return CommandResult(
                name=self.name,
                success=False,
                message="oneoff command requires a backend/model argument.",
            )

        arg_key = next(iter(args.keys()))

        # Use robust parsing that handles both slash and colon syntax
        backend, model = parse_model_backend(arg_key)
        if not backend:
            return CommandResult(
                name=self.name,
                success=False,
                message="Invalid format. Use backend/model or backend:model.",
            )

        backend = backend.strip()
        model = model.strip()

        if not backend or not model:
            return CommandResult(
                name=self.name,
                success=False,
                message="Backend and model cannot be empty.",
            )

        # Update the session state with the oneoff route
        new_state = session.state.backend_config.with_oneoff_route(backend, model)
        session.state = session.state.with_backend_config(new_state)

        return CommandResult(
            name=self.name,
            success=True,
            message=f"One-off route set to {backend}/{model}.",
        )
