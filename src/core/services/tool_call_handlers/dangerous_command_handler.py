"""
Dangerous Command Tool Call Handler.

Provides security enforcement against potentially destructive git commands
issued via local shell execution tools. Swallows such tool calls and returns
an instructive steering message back to the LLM.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    ToolCallContext,
    ToolCallReactionResult,
)
from src.core.services.dangerous_command_service import DangerousCommandService

logger = logging.getLogger(__name__)


class DangerousCommandHandler(IToolCallHandler):
    """Handler that blocks dangerous git-related local execution tool calls."""

    def __init__(
        self,
        dangerous_service: DangerousCommandService,
        steering_message: str | None = None,
        enabled: bool = True,
    ) -> None:
        self._service = dangerous_service
        self._enabled = enabled
        self._steering_message = steering_message or (
            "This is llm-interactive-proxy security enforcement module working on behalf "
            "user in charge. Your latest tool call has been intercepted and not forwarded "
            "to the agent. You were trying to execute a potentially dangerous command. "
            "This proxy won't pass any further potentially harmful tool calls to the agent, "
            "so don't try to repeat the latest call. Your only option if you want given "
            "command to be executed is to inform user that he needs to execute such command "
            "on he's own. You must also warn the user about potential destructive consequences "
            "of running of such command. Such information WILL get passed back to the user"
        )

    @property
    def name(self) -> str:
        return "dangerous_command_handler"

    @property
    def priority(self) -> int:
        # High priority so it runs before other generic handlers
        return 100

    async def can_handle(self, context: ToolCallContext) -> bool:
        if not self._enabled:
            return False

        tool_name: str = context.tool_name or ""
        arguments: Any = context.tool_arguments

        # Use service to detect dangerous command from tool name and arguments
        try:
            result = self._service.scan(tool_name, arguments)
            return result is not None
        except Exception:
            logger.warning(
                "DangerousCommandHandler.can_handle failed to scan arguments",
                exc_info=True,
            )
            return False

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        tool_name: str = context.tool_name or ""
        arguments: Any = context.tool_arguments

        scan_result = self._service.scan(tool_name, arguments)
        if scan_result is None:
            # Not dangerous after all; do not swallow
            return ToolCallReactionResult(should_swallow=False)

        rule, command = scan_result
        logger.warning(
            "Intercepted a potentially dangerous command. Rule=%s, Command='%s'",
            getattr(rule, "name", "unknown"),
            command,
        )

        return ToolCallReactionResult(
            should_swallow=True,
            replacement_response=self._steering_message,
            metadata={
                "handler": self.name,
                "rule": getattr(rule, "name", None),
                "command": command,
                "tool_name": tool_name,
                "source": "dangerous_command_reactor",
            },
        )
