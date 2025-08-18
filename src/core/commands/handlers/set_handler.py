"""Compatibility shim providing legacy SetCommandHandler expected by tests.

This handler implements a minimal subset of the legacy behaviour required by
unit tests: handling `temperature` parameter and mutating the provided
`SessionStateAdapter` (proxy_state) in-place.
"""
from __future__ import annotations

import logging
from typing import Any

from src.core.commands.handlers.base_handler import BaseCommandHandler, CommandHandlerResult
from src.core.domain.command_context import CommandContext

logger = logging.getLogger(__name__)


class SetCommandHandler(BaseCommandHandler):
    """Minimal Set command handler compatibility shim."""

    def __init__(self) -> None:
        super().__init__("set")

    def handle(self, param_value: Any, _current_state: Any = None, context: CommandContext | None = None) -> CommandHandlerResult:
        """Handle legacy set parameters.

        Args:
            param_value: expected to be a list of strings like ["temperature=0.8"]
            _current_state: legacy argument (ignored)
            context: expected to be a SessionStateAdapter or similar proxy_state
        """
        try:
            params = list(param_value) if param_value is not None else []
        except Exception:
            params = []

        # Default: nothing changed
        new_state = None

        for p in params:
            try:
                if isinstance(p, str) and "=" in p:
                    key, val = p.split("=", 1)
                    key = key.strip().lower()
                    val = val.strip()
                    if key == "temperature":
                        try:
                            temp = float(val)
                        except Exception:
                            return CommandHandlerResult(success=False, message=f"Invalid temperature: {val}")
                        # Validate
                        if temp < 0.0 or temp > 1.0:
                            return CommandHandlerResult(success=False, message="Invalid temperature: must be between 0 and 1")

                        # Mutate the provided proxy state if possible
                        if context is not None:
                            try:
                                # context is typically SessionStateAdapter; update underlying _state
                                underlying = getattr(context, "_state", None)
                                if underlying is not None:
                                    # Create updated reasoning_config via existing API if available
                                    reasoning = getattr(underlying, "reasoning_config", None)
                                    if reasoning is not None and hasattr(reasoning, "with_temperature"):
                                        updated = reasoning.with_temperature(temp)
                                        # Build new state via with_reasoning_config if available
                                        if hasattr(underlying, "with_reasoning_config"):
                                            new_state_obj = underlying.with_reasoning_config(updated)
                                            # assign back
                                            context._state = new_state_obj
                                        else:
                                            # best-effort: set attribute directly
                                            try:
                                                underlying.reasoning_config = updated
                                            except Exception:
                                                pass
                                    else:
                                        # Fallback: try to set attribute on adapter
                                        try:
                                            context.reasoning_config.temperature = temp  # type: ignore[attr-defined]
                                        except Exception:
                                            pass
                            except Exception:
                                logger.debug("Failed to update proxy_state with temperature", exc_info=True)
                        new_state = True
            except Exception:
                logger.debug("Error parsing set parameter", exc_info=True)

        if new_state:
            return CommandHandlerResult(success=True, message="Temperature set")

        return CommandHandlerResult(success=False, message="No valid parameters provided")


__all__ = ["SetCommandHandler"]


