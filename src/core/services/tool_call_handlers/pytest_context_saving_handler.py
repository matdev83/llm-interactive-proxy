"""Pytest Context Saving Handler.

This handler modifies pytest commands to include flags that provide a more
concise and useful output for LLM consumption. It adds `-r fE`, `-q`, and `--lf`
to pytest commands that do not already have them.

The feature is opt-in and controlled by a configuration flag.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    ToolCallContext,
    ToolCallReactionResult,
)
from src.core.services.tool_call_handlers.pytest_full_suite_handler import (
    _extract_command,
    _PYTEST_ROOT_PATTERN,
)

logger = logging.getLogger(__name__)


class PytestContextSavingHandler(IToolCallHandler):
    """Handler to modify pytest commands for context saving."""

    def __init__(self, enabled: bool = True):
        self._enabled = enabled

    @property
    def name(self) -> str:
        return "pytest_context_saving_handler"

    @property
    def priority(self) -> int:
        # Lower priority than PytestFullSuiteHandler to run after it.
        return 90

    async def can_handle(self, context: ToolCallContext) -> bool:
        if not self._enabled:
            return False

        command = _extract_command(context.tool_arguments)
        if not command:
            return False

        return bool(_PYTEST_ROOT_PATTERN.search(command))

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        if not self._enabled:
            return ToolCallReactionResult(should_swallow=False)

        command = _extract_command(context.tool_arguments)
        if not command:
            return ToolCallReactionResult(should_swallow=False)

        modified_command = self._add_pytest_flags(command)

        if modified_command != command:
            logger.info(
                "Modifying pytest command in session %s: '%s' -> '%s'",
                context.session_id,
                command,
                modified_command,
            )
            self._update_tool_arguments(context.tool_arguments, modified_command)

        return ToolCallReactionResult(should_swallow=False)

    def _add_pytest_flags(self, command: str) -> str:
        """Add context-saving flags to a pytest command."""
        tokens = command.split()
        
        # Using a set for efficient lookup
        flags_present = set(tokens)

        # Add -r fE if -r is not present
        if "-r" not in flags_present and not any(t.startswith("-r") for t in tokens):
            # Find index of pytest command
            pytest_index = -1
            for i, token in enumerate(tokens):
                if "pytest" in token:
                    pytest_index = i
                    break
            
            if pytest_index != -1:
                tokens.insert(pytest_index + 1, "-r fE")
                flags_present.add("-r fE")


        # Add -q if not present
        if "-q" not in flags_present and "--quiet" not in flags_present:
            pytest_index = -1
            for i, token in enumerate(tokens):
                if "pytest" in token:
                    pytest_index = i
                    break
            
            if pytest_index != -1:
                tokens.insert(pytest_index + 1, "-q")
                flags_present.add("-q")

        # Add --lf if not present
        if "--lf" not in flags_present and "--last-failed" not in flags_present:
            pytest_index = -1
            for i, token in enumerate(tokens):
                if "pytest" in token:
                    pytest_index = i
                    break
            
            if pytest_index != -1:
                tokens.insert(pytest_index + 1, "--lf")
                flags_present.add("--lf")

        return " ".join(tokens)

    def _update_tool_arguments(self, arguments: Any, new_command: str) -> None:
        """Update the tool arguments with the modified command."""
        if isinstance(arguments, dict):
            if "command" in arguments:
                arguments["command"] = new_command
            elif "cmd" in arguments:
                arguments["cmd"] = new_command
            elif "input" in arguments and isinstance(arguments["input"], str):
                arguments["input"] = new_command
            elif "args" in arguments and isinstance(arguments["args"], list):
                arguments["args"] = new_command.split()
            elif "args" in arguments and isinstance(arguments["args"], str):
                arguments["args"] = new_command
        elif isinstance(arguments, str):
            # This is tricky, as the original string could be JSON.
            # For now, we assume it's a simple command string.
            # A more robust solution would require deeper changes to the middleware.
            # This is a limitation we accept for now.
            # The problem is that we can't modify a string in place.
            # And we can't reassign context.tool_arguments.
            # We will rely on the arguments being a dict.
            logger.warning("Cannot update tool arguments when they are a plain string.")
