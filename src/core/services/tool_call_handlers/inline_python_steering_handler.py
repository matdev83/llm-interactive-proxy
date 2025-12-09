"""
Inline Python Steering Handler.

This handler intercepts tool calls that attempt to execute inline Python code
via shell commands (e.g., `python -c "..."`). It blocks these calls and returns
a steering message encouraging the use of temporary scripts instead, which are
more stable and less prone to terminal breakage.
"""

from __future__ import annotations

import logging
import re
from typing import Final

from src.core.domain.tool_constants import ShellExecutionTools
from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    ToolCallContext,
    ToolCallReactionResult,
)
from src.core.services.command_extraction_service import CommandExtractionService

logger = logging.getLogger(__name__)


class InlinePythonSteeringHandler(IToolCallHandler):
    """Handler that blocks inline Python execution attempts."""

    DEFAULT_MESSAGE: Final[str] = (
        "You were trying to use inline Python code. It tends to break terminals "
        "and is generally unstable. Please create a temporary script and run it instead"
    )

    # Matches `python -c` or `python.exe -c` with optional flags/args in between
    # Example matches:
    #   python -c "print('hello')"
    #   python.exe -c "..."
    #   python -u -c "..."
    #   python3 -c "..."
    _INLINE_PYTHON_PATTERN = re.compile(
        r"(?:^|[;&|\s])python(?:3|[\d\.]*)?(?:\.exe)?\s+(?:-[a-zA-Z0-9]+\s+)*-c\s+",
        re.IGNORECASE,
    )

    def __init__(
        self,
        message: str | None = None,
        enabled: bool = True,
    ) -> None:
        """Initialize the handler.

        Args:
            message: Custom steering message to return.
            enabled: Whether the handler is enabled.
        """
        self._message = message or self.DEFAULT_MESSAGE
        self._enabled = enabled
        self._command_service = CommandExtractionService()
        self._shell_tools = set(ShellExecutionTools.get_all())

    @property
    def name(self) -> str:
        return "inline_python_steering_handler"

    @property
    def priority(self) -> int:
        # High priority to catch this before general execution
        return 95

    async def can_handle(self, context: ToolCallContext) -> bool:
        if not self._enabled:
            return False

        tool_name = (context.tool_name or "").strip()

        # Check if tool is a known shell execution tool
        # (Exact match or regex match handled by CommandExtractionService if needed,
        # but here we stick to the specific list for precision as per other handlers)
        if (
            tool_name not in self._shell_tools
            and not self._command_service.is_shell_tool(tool_name)
        ):
            return False

        command = self._command_service.extract_command_string(context.tool_arguments)
        if not command:
            return False

        # Check for inline python pattern
        return bool(self._INLINE_PYTHON_PATTERN.search(command))

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        if not self._enabled:
            return ToolCallReactionResult(should_swallow=False)

        # Re-check to be safe/consistent, though reactor usually calls can_handle first
        command = self._command_service.extract_command_string(context.tool_arguments)
        if not command or not self._INLINE_PYTHON_PATTERN.search(command):
            return ToolCallReactionResult(should_swallow=False)

        logger.info(
            "Intercepted inline Python execution attempt in session %s",
            context.session_id,
        )

        return ToolCallReactionResult(
            should_swallow=True,
            replacement_response=self._message,
            metadata={
                "handler": self.name,
                "tool_name": context.tool_name,
                "command": command[:200],  # Log truncation
                "source": "inline_python_steering",
            },
        )
