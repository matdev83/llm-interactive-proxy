"""
Unset command handler for the SOLID architecture.

This module provides a command handler for unsetting configuration options.
"""

from __future__ import annotations

import logging
from typing import Any

from src.constants import DEFAULT_COMMAND_PREFIX
from src.core.commands.handlers.base_handler import (
    BaseCommandHandler,
    CommandHandlerResult,
)
from src.core.domain.command_context import CommandContext
from src.core.domain.configuration.session_state_builder import SessionStateBuilder
from src.core.domain.session import SessionState

logger = logging.getLogger(__name__)


class UnsetCommandHandler(BaseCommandHandler):
    """Handler for unsetting configuration options."""

    def __init__(self):
        """Initialize the unset command handler."""
        super().__init__("unset")
        self._handlers: dict[str, BaseCommandHandler] = {}

    @property
    def description(self) -> str:
        """Description of the command."""
        return "Unset previously configured options"

    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return [
            "!/unset(model)",
            "!/unset(interactive)",
            "!/unset(tool-loop-detection)",
            "!/unset(tool-loop-max-repeats, tool-loop-ttl, tool-loop-mode)",
        ]

    def register_handler(self, handler: BaseCommandHandler) -> None:
        """Register a specialized handler for a specific parameter.

        Args:
            handler: The handler to register
        """
        self._handlers[handler.name] = handler
        for alias in handler.aliases:
            self._handlers[alias] = handler
        logger.debug(f"Registered handler for {handler.name}")

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """
        return param_name.lower() == self.name

    def handle(
        self,
        param_value: Any,
        current_state: SessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle unsetting configuration values.

        Args:
            param_value: The parameter(s) to unset
            current_state: The current session state
            context: Optional command context

        Returns:
            A result containing success/failure status and updated state
        """
        if not param_value:
            return CommandHandlerResult(
                success=False,
                message="No parameters specified. Use unset(key1, key2, ...)",
            )

        # Convert param_value to a list of parameters
        if isinstance(param_value, dict):
            # If it's a dict, use the keys
            params = list(param_value.keys())
        elif isinstance(param_value, str):
            # If it's a string, split by commas
            params = [p.strip() for p in param_value.split(",")]
        elif isinstance(param_value, list):
            # If it's already a list, use it
            params = param_value
        else:
            # Otherwise, convert to string and use as a single parameter
            params = [str(param_value)]

        # Track results for each parameter
        results = []
        success = True

        # Use SessionStateBuilder to build up changes
        builder = SessionStateBuilder(current_state)

        # Process each parameter
        for param in params:
            param_lower = param.lower()

            # Check if we have a specialized handler for this parameter
            if param_lower in self._handlers:
                handler = self._handlers[param_lower]
                handler_result = handler.handle(None, current_state)
                results.append(handler_result.message)

                if handler_result.new_state:
                    # Update the builder with the new state
                    builder = SessionStateBuilder(handler_result.new_state)

                if not handler_result.success:
                    success = False
            else:
                # Handle common parameters directly
                try:
                    if param_lower == "model" or param_lower == "backend_model":
                        builder.with_backend_config(
                            current_state.backend_config.with_model(None)
                        )
                        results.append("Model unset")

                    elif param_lower == "backend" or param_lower == "backend_type":
                        builder.with_backend_config(
                            current_state.backend_config.without_override()
                        )
                        results.append("Backend unset")

                    elif (
                        param_lower == "interactive"
                        or param_lower == "interactive-mode"
                    ):
                        builder.with_backend_config(
                            current_state.backend_config.with_interactive_mode(True)
                        )
                        results.append("Interactive mode reset to default (enabled)")

                    elif param_lower == "temperature":
                        builder.with_reasoning_config(
                            current_state.reasoning_config.with_temperature(None)
                        )
                        results.append("Temperature unset")

                    elif param_lower == "reasoning-effort":
                        builder.with_reasoning_config(
                            current_state.reasoning_config.with_reasoning_effort(None)
                        )
                        results.append("Reasoning effort unset")

                    elif param_lower == "thinking-budget":
                        builder.with_reasoning_config(
                            current_state.reasoning_config.with_thinking_budget(None)
                        )
                        results.append("Thinking budget unset")

                    elif param_lower == "gemini-generation-config":
                        builder.with_reasoning_config(
                            current_state.reasoning_config.with_gemini_generation_config(
                                None
                            )
                        )
                        results.append("Gemini generation config unset")

                    elif param_lower == "openai_url" or param_lower == "openai-url":
                        builder.with_backend_config(
                            current_state.backend_config.with_openai_url(None)
                        )
                        results.append("OpenAI URL unset")

                    elif param_lower == "project":
                        builder.with_project(None)
                        results.append("Project unset")

                    elif param_lower == "project-dir" or param_lower == "project_dir":
                        builder.with_project_dir(None)
                        results.append("Project directory unset")

                    elif param_lower == "loop-detection":
                        builder.with_loop_config(
                            current_state.loop_config.with_loop_detection_enabled(True)
                        )
                        results.append("Loop detection reset to default (enabled)")

                    elif param_lower == "tool-loop-detection":
                        builder.with_loop_config(
                            current_state.loop_config.with_tool_loop_detection_enabled(
                                True
                            )
                        )
                        results.append("Tool loop detection reset to default (enabled)")

                    elif param_lower == "tool-loop-max-repeats":
                        builder.with_loop_config(
                            current_state.loop_config.with_tool_loop_max_repeats(None)
                        )
                        results.append("Tool loop max repeats unset")

                    elif param_lower == "tool-loop-ttl":
                        builder.with_loop_config(
                            current_state.loop_config.with_tool_loop_ttl(None)
                        )
                        results.append("Tool loop TTL unset")

                    elif param_lower == "tool-loop-mode":
                        builder.with_loop_config(
                            current_state.loop_config.with_tool_loop_mode(None)
                        )
                        results.append("Tool loop mode unset")

                    elif param_lower == "command-prefix":
                        # This is a special case that requires app state
                        if context and hasattr(context, "app") and context.app:
                            context.app.state.command_prefix = DEFAULT_COMMAND_PREFIX
                            results.append(
                                f"Command prefix reset to {DEFAULT_COMMAND_PREFIX}"
                            )
                        else:
                            results.append(
                                "Cannot unset command prefix without app context"
                            )
                            success = False

                    else:
                        results.append(f"Unknown parameter: {param}")
                        success = False

                except Exception as e:
                    logger.exception(f"Error unsetting parameter {param}: {e}")
                    results.append(f"Error unsetting {param}: {e}")
                    success = False

        # Build the final state
        new_state = builder.build()

        # Build the result message
        result_message = "; ".join(results)

        return CommandHandlerResult(
            success=success,
            message=result_message if result_message else "Settings unset.",
            new_state=new_state,
        )
