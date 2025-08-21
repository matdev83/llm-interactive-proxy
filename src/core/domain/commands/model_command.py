from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.constants import COMMAND_EXECUTION_ERROR
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.secure_base_command import StatelessCommandBase
from src.core.domain.session import Session

logger = logging.getLogger(__name__)


class ModelCommand(StatelessCommandBase, BaseCommand):
    """Command for setting the model name."""

    def __init__(self):
        """Initialize without state services."""
        StatelessCommandBase.__init__(self)

    @property
    def name(self) -> str:
        return "model"

    @property
    def format(self) -> str:
        return "model(name=<model-name>)"

    @property
    def description(self) -> str:
        return "Change the active model for LLM requests"

    @property
    def examples(self) -> list[str]:
        return ["!/model(name=gpt-4)", "!/model(name=openrouter:gpt-4)"]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Set or unset the model name."""
        model_name = args.get("name")

        if model_name is None or (
            isinstance(model_name, str) and not model_name.strip()
        ):
            return self._unset_model(session)

        return self._set_model(model_name, session)

    def _unset_model(self, session: Session) -> CommandResult:
        """Unsets the model override."""
        try:
            backend_config = session.state.backend_config.with_model(None)
            updated_state = session.state.with_backend_config(backend_config)
            return CommandResult(
                name=self.name,
                success=True,
                message="Model unset",
                new_state=updated_state,
            )
        except Exception as e:
            error_message = COMMAND_EXECUTION_ERROR.format(error=str(e))
            logger.error(error_message)
            return CommandResult(
                success=False, message=error_message, name=self.name
            )

    def _set_model(self, model_name: str, session: Session) -> CommandResult:
        """Sets the model, potentially with a backend override."""
        try:
            backend_type = None
            actual_model = model_name

            if ":" in model_name:
                backend_type, actual_model = model_name.split(":", 1)

            backend_config = session.state.backend_config.with_model(actual_model)
            if backend_type:
                backend_config = backend_config.with_backend(backend_type)

            updated_state = session.state.with_backend_config(backend_config)

            message_parts = []
            if backend_type:
                message_parts.append(f"Backend changed to {backend_type}")
            message_parts.append(f"Model changed to {actual_model}")

            return CommandResult(
                name=self.name,
                success=True,
                message="; ".join(message_parts),
                data={"model": actual_model, "backend": backend_type},
                new_state=updated_state,
            )
        except Exception as e:
            error_message = COMMAND_EXECUTION_ERROR.format(error=str(e))
            logger.error(error_message)
            return CommandResult(
                success=False, message=error_message, name=self.name
            )
