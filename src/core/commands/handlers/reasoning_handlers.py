"""
Reasoning setting handlers for the SOLID architecture.

This module provides command handlers for reasoning-related settings.
"""

from __future__ import annotations

import ast
import json
import logging
from typing import Any

from src.core.commands.handlers.base_handler import (
    BaseCommandHandler,
    CommandHandlerResult,
)
from src.core.domain.command_context import CommandContext
from src.core.interfaces.domain_entities_interface import ISessionState

logger = logging.getLogger(__name__)


class ReasoningEffortHandler(BaseCommandHandler):
    """Handler for setting the reasoning effort level."""

    def __init__(self) -> None:
        """Initialize the reasoning effort handler."""
        super().__init__("reasoning-effort")

    @property
    def aliases(self) -> list[str]:
        """Aliases for the parameter name."""
        return ["reasoning_effort", "reasoning"]

    @property
    def description(self) -> str:
        """Description of the command."""
        return "Set the reasoning effort level (low, medium, high, maximum)"

    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return [
            "!/set(reasoning-effort=low)",
            "!/set(reasoning-effort=medium)",
            "!/set(reasoning-effort=high)",
            "!/set(reasoning-effort=maximum)",
        ]

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """
        normalized = param_name.lower().replace("_", "-").replace(" ", "-")
        return normalized == self.name or normalized in [
            a.lower() for a in self.aliases
        ]

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle setting the reasoning effort level.

        Args:
            param_value: The reasoning effort level
            current_state: The current session state
            context: Optional command context

        Returns:
            A result containing success/failure status and updated state
        """
        # Check if CLI thinking budget is set - if so, block reasoning effort changes
        # because CLI --thinking-budget should override all reasoning settings
        if _is_cli_thinking_budget_enabled():
            return CommandHandlerResult(
                success=False,
                message="Cannot change reasoning effort when --thinking-budget CLI parameter is set. CLI settings take priority over interactive commands.",
            )

        if not param_value:
            return CommandHandlerResult(
                success=False, message="Reasoning effort level must be specified"
            )

        effort = str(param_value).lower()
        if effort not in ("low", "medium", "high", "maximum"):
            return CommandHandlerResult(
                success=False,
                message=f"Invalid reasoning effort: {param_value}. Use low, medium, high, or maximum.",
            )

        # Create new state with updated reasoning effort
        new_state = current_state.with_reasoning_config(
            current_state.reasoning_config.with_reasoning_effort(effort)
        )

        return CommandHandlerResult(
            success=True,
            message=f"Reasoning effort set to {effort}",
            new_state=new_state,
        )


class ThinkingBudgetHandler(BaseCommandHandler):
    """Handler for setting the thinking budget."""

    def __init__(self) -> None:
        """Initialize the thinking budget handler."""
        super().__init__("thinking-budget")

    @property
    def aliases(self) -> list[str]:
        """Aliases for the parameter name."""
        return ["thinking_budget", "budget"]

    @property
    def description(self) -> str:
        """Description of the command."""
        return "Set the thinking budget in tokens (128-32768)"

    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return ["!/set(thinking-budget=1024)", "!/set(thinking-budget=2048)"]

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """
        normalized = param_name.lower().replace("_", "-").replace(" ", "-")
        return normalized == self.name or normalized in [
            a.lower() for a in self.aliases
        ]

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle setting the thinking budget.

        Args:
            param_value: The thinking budget in tokens
            current_state: The current session state
            context: Optional command context

        Returns:
            A result containing success/failure status and updated state
        """
        # Check if CLI thinking budget is set - if so, block interactive changes
        if _is_cli_thinking_budget_enabled():
            return CommandHandlerResult(
                success=False,
                message="Cannot change thinking budget when --thinking-budget CLI parameter is set. CLI settings take priority over interactive commands.",
            )

        if not param_value:
            return CommandHandlerResult(
                success=False, message="Thinking budget must be specified"
            )

        try:
            budget = int(param_value)
            if budget < 128 or budget > 32768:
                return CommandHandlerResult(
                    success=False,
                    message="Thinking budget must be between 128 and 32768 tokens",
                )
        except ValueError:
            return CommandHandlerResult(
                success=False,
                message=f"Invalid thinking budget: {param_value}. Must be an integer.",
            )

        # Create new state with updated thinking budget
        new_state = current_state.with_reasoning_config(
            current_state.reasoning_config.with_thinking_budget(budget)
        )

        return CommandHandlerResult(
            success=True,
            message=f"Thinking budget set to {budget}",
            new_state=new_state,
        )


class GeminiGenerationConfigHandler(BaseCommandHandler):
    """Handler for setting the Gemini generation config."""

    def __init__(self) -> None:
        """Initialize the Gemini generation config handler."""
        super().__init__("gemini-generation-config")

    @property
    def aliases(self) -> list[str]:
        """Aliases for the parameter name."""
        return ["gemini_generation_config", "gemini_config"]

    @property
    def description(self) -> str:
        """Description of the command."""
        return "Set the Gemini generation config as a JSON object"

    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return [
            "!/set(gemini-generation-config={'thinkingConfig': {'thinkingBudget': 1024}})"
        ]

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """
        normalized = param_name.lower().replace("_", "-").replace(" ", "-")
        return normalized == self.name or normalized in [
            a.lower() for a in self.aliases
        ]

    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle setting the Gemini generation config.

        Args:
            param_value: The Gemini generation config as a JSON string or object
            current_state: The current session state
            context: Optional command context

        Returns:
            A result containing success/failure status and updated state
        """
        if not param_value:
            return CommandHandlerResult(
                success=False, message="Gemini generation config must be specified"
            )

        try:
            # Parse the config if it's a string
            if isinstance(param_value, str):
                try:
                    config = json.loads(param_value)
                except json.JSONDecodeError as json_error:
                    try:
                        config = ast.literal_eval(param_value)
                    except (ValueError, SyntaxError):
                        return CommandHandlerResult(
                            success=False, message=f"Invalid JSON: {json_error}"
                        )
            else:
                config = param_value

            # Validate that it's a dict
            if not isinstance(config, dict):
                return CommandHandlerResult(
                    success=False,
                    message="Invalid Gemini generation config: must be a JSON object",
                )
        except json.JSONDecodeError as e:
            return CommandHandlerResult(success=False, message=f"Invalid JSON: {e}")

        # Create new state with updated Gemini generation config
        new_state = current_state.with_reasoning_config(
            current_state.reasoning_config.with_gemini_generation_config(config)
        )

        return CommandHandlerResult(
            success=True,
            message=f"Gemini generation config set to {config}",
            new_state=new_state,
        )


def _is_cli_thinking_budget_enabled() -> bool:
    """Check if CLI thinking budget is enabled via --thinking-budget parameter."""
    import os

    # Check if thinking budget was set via CLI (stored in environment)
    thinking_budget = os.environ.get("THINKING_BUDGET")
    return thinking_budget is not None and thinking_budget.strip() != ""
