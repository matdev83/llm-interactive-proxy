"""
Unset command implementation.

This module provides a domain command for unsetting (clearing) various session parameters.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.secure_base_command import StatefulCommandBase
from src.core.domain.configuration.reasoning_config import ReasoningConfiguration
from src.core.domain.session import Session
from src.core.interfaces.domain_entities_interface import ISessionState
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
)

logger = logging.getLogger(__name__)


class UnsetCommand(StatefulCommandBase, BaseCommand):
    """Command for unsetting (clearing) various session parameters."""

    def __init__(
        self,
        state_reader: ISecureStateAccess,
        state_modifier: ISecureStateModification | None = None,
    ):
        """Initialize with required state services."""
        StatefulCommandBase.__init__(self, state_reader, state_modifier)
        self._setup_handlers()

    @property
    def name(self) -> str:
        return "unset"

    @property
    def format(self) -> str:
        return "unset(parameter)"

    @property
    def description(self) -> str:
        return "Unset (clear) various parameters for the session"

    @property
    def examples(self) -> list[str]:
        return ["!/unset(model)", "!/unset(temperature)"]

    def _setup_handlers(self) -> None:
        """Set up parameter handlers."""
        self.param_handlers = {
            "backend": self._unset_backend,
            "model": self._unset_model,
            "temperature": self._unset_temperature,
            "interactive-mode": self._unset_interactive_mode,
            "interactive": self._unset_interactive_mode,  # Alias
            "redact-api-keys-in-prompts": self._unset_redact_api_keys,
            "command-prefix": self._unset_command_prefix,
            "project": self._unset_project,
        }

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Unset various session parameters."""
        # Validate that this command was created through proper DI
        self._validate_di_usage()

        if not args or all(not v for v in args.values()):
            return CommandResult(
                success=False,
                message="Parameter to unset must be specified",
                name=self.name,
            )

        parameters_to_unset = [p for p, v in args.items() if v]
        if not parameters_to_unset:
            return CommandResult(
                success=False,
                message="Parameter to unset must be specified",
                name=self.name,
            )

        updated_state = session.state
        messages: list[str] = []
        data: dict[str, Any] = {}
        success_count = 0

        for param in parameters_to_unset:
            handler = self.param_handlers.get(param)
            if handler:
                result, new_state = handler(updated_state, context)
                updated_state = new_state
                messages.append(result.message)
                if result.data:
                    data.update(result.data)
                success_count += 1
            else:
                messages.append(f"Unknown parameter: {param}")

        if success_count == 0:
            return CommandResult(
                success=False, message="unset: nothing to do", name=self.name
            )

        return CommandResult(
            success=True,
            message="\n".join(messages),
            name=self.name,
            data=data,
            new_state=updated_state,
        )

    def _unset_backend(
        self, state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        new_backend_config = state.backend_config.without_override()
        updated_state = state.with_backend_config(new_backend_config)
        result = CommandResult(
            success=True, message="Backend reset to default", data={"backend": None}
        )
        return result, updated_state

    def _unset_model(
        self, state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        new_backend_config = state.backend_config.with_model(None)
        updated_state = state.with_backend_config(new_backend_config)
        result = CommandResult(
            success=True, message="Model reset to default", data={"model": None}
        )
        return result, updated_state

    def _unset_temperature(
        self, state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        default_temp = ReasoningConfiguration().temperature
        reasoning_config = state.reasoning_config.with_temperature(default_temp)
        updated_state = state.with_reasoning_config(reasoning_config)
        result = CommandResult(
            success=True,
            message=f"Temperature reset to default ({default_temp})",
            data={"temperature": default_temp},
        )
        return result, updated_state

    def _unset_interactive_mode(
        self, state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        new_backend_config = state.backend_config.with_interactive_mode(True)
        updated_state = state.with_backend_config(
            new_backend_config
        ).with_interactive_just_enabled(False)
        result = CommandResult(
            success=True,
            message="Interactive mode reset to default (enabled)",
            data={"interactive-mode": True},
        )
        return result, updated_state

    def _unset_redact_api_keys(
        self, state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        updated_state = state.with_api_key_redaction_enabled(None)

        result = CommandResult(
            success=True,
            message="API key redaction reset to default",
            data={"redact-api-keys-in-prompts": None},
        )
        return result, updated_state

    def _unset_command_prefix(
        self, state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        updated_state = state.with_command_prefix(None)

        result = CommandResult(
            success=True,
            message="Command prefix reset to default (!/)",
            data={"command-prefix": "!/"},
            new_state=updated_state,
        )
        return result, updated_state

    def _unset_project(
        self, state: ISessionState, context: Any
    ) -> tuple[CommandResult, ISessionState]:
        updated_state = state.with_project(None)
        result = CommandResult(
            success=True, message="Project reset to default", data={"project": None}
        )
        return result, updated_state
