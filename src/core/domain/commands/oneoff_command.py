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

        route_value = self._extract_route_argument(args)
        if not route_value:
            return CommandResult(
                name=self.name,
                success=False,
                message="Invalid format. Use backend/model or backend:model.",
            )

        # Use robust parsing that handles both slash and colon syntax
        backend, model = parse_model_backend(route_value)
        if not backend or not model:
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

    def _extract_route_argument(self, args: Mapping[str, Any]) -> str | None:
        """Extract the backend/model argument from parsed command args."""

        candidate_keys = ("element", "value", "route", "target")
        for key in candidate_keys:
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for key, value in args.items():
            if isinstance(key, str):
                key_str = key.strip()
                if key_str and ("/" in key_str or ":" in key_str):
                    return key_str

            if isinstance(value, str):
                value_str = value.strip()
                if value_str and ("/" in value_str or ":" in value_str):
                    return value_str

            if value is True and isinstance(key, str):
                key_str = key.strip()
                if key_str and ("/" in key_str or ":" in key_str):
                    return key_str

        return None
