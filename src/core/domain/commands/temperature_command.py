from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session

logger = logging.getLogger(__name__)

class TemperatureCommand(BaseCommand):
    """Command for setting the temperature value."""

    name = "temperature"
    format = "temperature(value=0.0-1.0)"
    description = "Change the temperature setting for LLM requests"
    examples = ["!/temperature(value=0.7)"]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Set the temperature value."""
        temp_value = args.get("value")
        if temp_value is None:
            return CommandResult(
                success=False, message="Temperature value must be specified", name=self.name
            )

        try:
            temp_float = float(temp_value)
            if not (0 <= temp_float <= 1):
                return CommandResult(
                    success=False,
                    message="Temperature must be between 0.0 and 1.0",
                    name=self.name,
                )

            reasoning_config = session.state.reasoning_config.with_temperature(temp_float)
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
                success=False, message="Temperature must be a valid number", name=self.name
            )
        except Exception as e:
            logger.error(f"Error setting temperature: {e}")
            return CommandResult(
                success=False, message=f"Error setting temperature: {e}", name=self.name
            )