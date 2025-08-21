from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.constants import (
    COMMAND_EXECUTION_ERROR,
)
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.secure_base_command import StatelessCommandBase
from src.core.domain.session import Session

logger = logging.getLogger(__name__)


class TemperatureCommand(StatelessCommandBase, BaseCommand):
    """Command for setting the temperature value."""

    def __init__(self):
        """Initialize without state services."""
        StatelessCommandBase.__init__(self)

    @property
    def name(self) -> str:
        return "temperature"

    @property
    def format(self) -> str:
        return "temperature(value=0.0-1.0)"

    @property
    def description(self) -> str:
        return "Change the temperature setting for LLM requests"

    @property
    def examples(self) -> list[str]:
        return ["!/temperature(value=0.7)"]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Set the temperature value."""
        temp_value = args.get("value")
        if temp_value is None:
            return CommandResult(
                success=False,
                message="Temperature value must be specified",
                name=self.name,
            )

        try:
            temp_float = float(temp_value)
            if not (0 <= temp_float <= 1):
                return CommandResult(
                    success=False,
                    message="Temperature must be between 0.0 and 1.0",
                    name=self.name,
                )

            reasoning_config = session.state.reasoning_config.with_temperature(
                temp_float
            )
            updated_state = session.state.with_reasoning_config(reasoning_config)

            return CommandResult(
                success=True,
                message=f"Temperature set to {temp_float}",
                name=self.name,
                data={"temperature": temp_float},
                new_state=updated_state,
            )
        except (ValueError, TypeError):
            return CommandResult(
                success=False,
                message="Temperature must be a valid number",
                name=self.name,
            )
        except Exception as e:
            error_message = COMMAND_EXECUTION_ERROR.format(error=str(e))
            logger.error(error_message)
            return CommandResult(
                success=False, message=error_message, name=self.name
            )
