"""
Temperature command implementation.

This module provides a domain command for setting the temperature value.
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


class TemperatureCommand(BaseCommand):
    """Command for setting the temperature value."""

    name = "temperature"
    format = "temperature([value=0.0-1.0])"
    description = "Change the temperature setting for LLM requests"
    examples = [
        "!/temperature(value=0.7)",
        "!/temperature(value=0)",
        "!/temperature(value=1.0)",
    ]

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Set the temperature value.

        Args:
            args: Command arguments with temperature value
            session: Current session
            context: Additional context data

        Returns:
            CommandResult indicating success or failure
        """
        temp_value = args.get("value")
        if not temp_value:
            return CommandResult(
                success=False,
                message="Temperature value must be specified",
                name=self.name,
            )

        try:
            # Convert to float and validate range
            temp_float = float(temp_value)
            if temp_float < 0 or temp_float > 1:
                return CommandResult(
                    success=False,
                    message="Temperature must be between 0.0 and 1.0",
                    name=self.name,
                )

            # Create new reasoning config with updated temperature
            reasoning_config = session.state.reasoning_config.with_temperature(
                temp_float
            )

            # Cast to concrete type
            concrete_reasoning_config = cast(ReasoningConfiguration, reasoning_config)

            # Create new session state with updated reasoning config
            updated_state: ISessionState
            if isinstance(session.state, SessionStateAdapter):
                # Working with SessionStateAdapter - get the underlying state
                old_state = session.state._state
                new_state = old_state.with_reasoning_config(concrete_reasoning_config)
                updated_state = SessionStateAdapter(new_state)
            elif isinstance(session.state, SessionState):
                # Working with SessionState directly
                new_state = session.state.with_reasoning_config(
                    concrete_reasoning_config
                )
                updated_state = SessionStateAdapter(new_state)
            else:
                # Fallback for other implementations
                updated_state = session.state

            return CommandResult(
                success=True,
                message=f"Temperature set to {temp_float}",
                name=self.name,
                data={"temperature": temp_float},
                new_state=updated_state,
            )
        except ValueError:
            return CommandResult(
                success=False,
                message="Temperature must be a valid number",
                name=self.name,
            )
        except Exception as e:
            logger.error(f"Error setting temperature: {e}")
            return CommandResult(
                success=False,
                message=f"Error setting temperature: {e}",
                name=self.name,
            )
