"""
Set command handler for the SOLID architecture.

This module provides a unified command handler for setting various configuration options.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.core.commands.handlers.base_handler import (
    BaseCommandHandler,
    CommandHandlerResult,
)
from src.core.domain.command_context import CommandContext
from src.core.domain.configuration.session_state_builder import SessionStateBuilder
from src.core.domain.session import SessionState

logger = logging.getLogger(__name__)


class SetCommandHandler(BaseCommandHandler):
    """Unified handler for setting various configuration options."""

    def __init__(self):
        """Initialize the set command handler."""
        super().__init__("set")
        self._handlers: dict[str, BaseCommandHandler] = {}

    @property
    def description(self) -> str:
        """Description of the command."""
        return "Set session or global configuration values"

    @property
    def examples(self) -> list[str]:
        """Examples of using this command."""
        return [
            "!/set(model=openrouter:gpt-4)",
            "!/set(interactive=true)",
            "!/set(reasoning-effort=high)",
            "!/set(thinking-budget=2048)",
            "!/set(gemini-generation-config={'thinkingConfig': {'thinkingBudget': 1024}})",
            "!/set(temperature=0.7)",
            "!/set(openai_url=https://api.example.com/v1)",
            "!/set(loop-detection=true)",
            "!/set(tool-loop-detection=true)",
            "!/set(tool-loop-max-repeats=4)",
            "!/set(tool-loop-ttl=120)",
            "!/set(tool-loop-mode=break)",
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

    def _parse_bool(self, value: str) -> bool | None:
        """Parse a boolean value from a string.

        Args:
            value: The string to parse

        Returns:
            The parsed boolean value or None if parsing fails
        """
        val = value.strip().lower()
        if val in ("true", "1", "yes", "on"):
            return True
        if val in ("false", "0", "no", "off", "none"):
            return False
        return None

    def _parse_json(self, value: str) -> Any:
        """Parse a JSON value from a string.

        Args:
            value: The string to parse

        Returns:
            The parsed JSON value

        Raises:
            ValueError: If the string is not valid JSON
        """
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")

    def handle(
        self,
        param_value: Any,
        current_state: SessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle setting configuration values.

        Args:
            param_value: The parameter values to set
            current_state: The current session state
            context: Optional command context

        Returns:
            A result containing success/failure status and updated state
        """
        if not param_value:
            return CommandHandlerResult(
                success=False,
                message="No parameters specified. Use set(key=value, ...)",
            )

        # Convert param_value to a dictionary if it's not already
        if isinstance(param_value, dict):
            params = param_value
        else:
            # Try to parse as a single key=value pair
            try:
                key, value = str(param_value).split("=", 1)
                params = {key: value}
            except ValueError:
                return CommandHandlerResult(
                    success=False,
                    message=f"Invalid format: {param_value}. Use key=value format.",
                )

        # Track results for each parameter
        results = []
        success = True

        # Use SessionStateBuilder to build up changes
        builder = SessionStateBuilder(current_state)

        # Process each parameter
        for param, value in params.items():
            param_lower = param.lower()

            # Check if we have a specialized handler for this parameter
            if param_lower in self._handlers:
                handler = self._handlers[param_lower]
                handler_result = handler.handle(value, current_state)
                results.append(handler_result.message)

                if handler_result.new_state:
                    # Update the builder with the new state
                    builder = SessionStateBuilder(handler_result.new_state)

                if not handler_result.success:
                    success = False
            else:
                # Handle common parameters directly
                try:
                    if (
                        param_lower == "interactive"
                        or param_lower == "interactive-mode"
                    ):
                        bool_value = self._parse_bool(str(value))
                        if bool_value is None:
                            results.append(
                                f"Invalid boolean value for {param}: {value}"
                            )
                            success = False
                        else:
                            builder.with_backend_config(
                                current_state.backend_config.with_interactive_mode(
                                    bool_value
                                )
                            )
                            results.append(f"Interactive mode set to {bool_value}")

                    elif param_lower == "reasoning-effort":
                        effort = str(value).lower()
                        if effort not in ("low", "medium", "high", "maximum"):
                            results.append(
                                f"Invalid reasoning effort: {value}. Use low, medium, high, or maximum."
                            )
                            success = False
                        else:
                            builder.with_reasoning_config(
                                current_state.reasoning_config.with_reasoning_effort(
                                    effort
                                )
                            )
                            results.append(f"Reasoning effort set to {effort}")

                    elif param_lower == "thinking-budget":
                        try:
                            budget = int(value)
                            builder.with_reasoning_config(
                                current_state.reasoning_config.with_thinking_budget(
                                    budget
                                )
                            )
                            results.append(f"Thinking budget set to {budget}")
                        except ValueError:
                            results.append(
                                f"Invalid thinking budget: {value}. Must be an integer."
                            )
                            success = False

                    elif param_lower == "model":
                        model_name = str(value)
                        from src.core.domain.configuration.backend_config import (
                            BackendConfiguration,
                        )

                        builder.with_backend_config(
                            BackendConfiguration.model_validate(
                                current_state.backend_config
                            ).with_model(model_name)
                        )
                        results.append(f"model set to {model_name}")

                    elif param_lower == "backend":
                        backend_name = str(value)
                        from src.core.domain.configuration.backend_config import (
                            BackendConfiguration,
                        )

                        builder.with_backend_config(
                            BackendConfiguration.model_validate(
                                current_state.backend_config
                            ).with_backend(backend_name)
                        )
                        results.append(f"backend set to {backend_name}")

                    elif param_lower == "gemini-generation-config":
                        try:
                            config = self._parse_json(str(value))
                            from src.core.domain.configuration.reasoning_config import (
                                ReasoningConfiguration,
                            )

                            builder.with_reasoning_config(
                                ReasoningConfiguration.model_validate(
                                    current_state.reasoning_config
                                ).with_gemini_generation_config(config)
                            )
                            results.append(f"Gemini generation config set to {config}")
                        except ValueError as e:
                            results.append(f"Invalid Gemini generation config: {e}")
                            success = False

                    elif param_lower == "openai_url" or param_lower == "openai-url":
                        url = str(value)
                        from src.core.domain.configuration.backend_config import (
                            BackendConfiguration,
                        )

                        builder.with_backend_config(
                            BackendConfiguration.model_validate(
                                current_state.backend_config
                            ).with_openai_url(url)
                        )
                        results.append(f"OpenAI URL set to {url}")

                    elif param_lower == "loop-detection":
                        bool_value = self._parse_bool(str(value))
                        if bool_value is None:
                            results.append(
                                f"Invalid boolean value for {param}: {value}"
                            )
                            success = False
                        else:
                            from src.core.domain.configuration.loop_detection_config import (
                                LoopDetectionConfiguration,
                            )

                            builder.with_loop_config(
                                LoopDetectionConfiguration.model_validate(
                                    current_state.loop_config
                                ).with_loop_detection_enabled(bool_value)
                            )
                            results.append(f"Loop detection set to {bool_value}")

                    elif param_lower == "tool-loop-detection":
                        bool_value = self._parse_bool(str(value))
                        if bool_value is None:
                            results.append(
                                f"Invalid boolean value for {param}: {value}"
                            )
                            success = False
                        else:
                            from src.core.domain.configuration.loop_detection_config import (
                                LoopDetectionConfiguration,
                            )

                            builder.with_loop_config(
                                LoopDetectionConfiguration.model_validate(
                                    current_state.loop_config
                                ).with_tool_loop_detection_enabled(bool_value)
                            )
                            results.append(f"Tool loop detection set to {bool_value}")

                    elif param_lower == "tool-loop-max-repeats":
                        try:
                            repeats = int(value)
                            from src.core.domain.configuration.loop_detection_config import (
                                LoopDetectionConfiguration,
                            )

                            builder.with_loop_config(
                                LoopDetectionConfiguration.model_validate(
                                    current_state.loop_config
                                ).with_tool_loop_max_repeats(repeats)
                            )
                            results.append(f"Tool loop max repeats set to {repeats}")
                        except ValueError:
                            results.append(
                                f"Invalid tool loop max repeats: {value}. Must be an integer."
                            )
                            success = False

                    elif param_lower == "tool-loop-ttl":
                        try:
                            ttl = int(value)
                            from src.core.domain.configuration.loop_detection_config import (
                                LoopDetectionConfiguration,
                            )

                            builder.with_loop_config(
                                LoopDetectionConfiguration.model_validate(
                                    current_state.loop_config
                                ).with_tool_loop_ttl_seconds(ttl)
                            )
                            results.append(f"Tool loop TTL set to {ttl} seconds")
                        except ValueError:
                            results.append(
                                f"Invalid tool loop TTL: {value}. Must be an integer."
                            )
                            success = False

                    elif param_lower == "tool-loop-mode":
                        mode = str(value).lower()
                        if mode not in ("break", "chance_then_break"):
                            results.append(
                                f"Invalid tool loop mode: {value}. Use break or chance_then_break."
                            )
                            success = False
                        else:
                            from src.tool_call_loop.config import ToolLoopMode

                            tool_mode = (
                                ToolLoopMode.BREAK
                                if mode == "break"
                                else ToolLoopMode.CHANCE_THEN_BREAK
                            )
                            from src.core.domain.configuration.loop_detection_config import (
                                LoopDetectionConfiguration,
                            )

                            builder.with_loop_config(
                                LoopDetectionConfiguration.model_validate(
                                    current_state.loop_config
                                ).with_tool_loop_mode(tool_mode)
                            )
                            results.append(f"Tool loop mode set to {mode}")

                    elif param_lower == "temperature":
                        try:
                            temp_value = float(value)
                            if temp_value < 0.0 or temp_value > 2.0:
                                results.append(
                                    f"Invalid temperature value: {value}. Must be between 0.0 and 2.0."
                                )
                                success = False
                            else:
                                from src.core.domain.configuration.reasoning_config import (
                                    ReasoningConfiguration,
                                )

                                builder.with_reasoning_config(
                                    ReasoningConfiguration.model_validate(
                                        current_state.reasoning_config
                                    ).with_temperature(temp_value)
                                )
                                results.append(f"Temperature set to {temp_value}")
                        except ValueError:
                            results.append(
                                f"Invalid temperature value: {value}. Must be a number."
                            )
                            success = False

                    else:
                        results.append(f"Unknown parameter: {param}")
                        success = False

                except Exception as e:
                    logger.exception(f"Error processing parameter {param}: {e}")
                    results.append(f"Error processing {param}: {e}")
                    success = False

        # Build the final state
        new_state = builder.build()

        # Build the result message
        result_message = "; ".join(results)

        return CommandHandlerResult(
            success=success,
            message=result_message if result_message else "Settings processed.",
            new_state=new_state,
        )
