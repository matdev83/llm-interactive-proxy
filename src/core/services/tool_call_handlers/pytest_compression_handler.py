"""
Pytest Compression Tool Call Handler.

Detects when LLM sends tool calls containing pytest commands and sets
compression state for the next tool call reply. This implements a state
machine pattern where tool call detection triggers state changes for
response compression.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    ToolCallContext,
    ToolCallReactionResult,
)
from src.core.services.pytest_compression_service import PytestCompressionService

logger = logging.getLogger(__name__)


class PytestCompressionHandler(IToolCallHandler):
    """Handler that detects pytest commands and sets compression state."""

    def __init__(
        self,
        pytest_compression_service: PytestCompressionService,
        session_service,
        enabled: bool = True,
    ) -> None:
        self._service = pytest_compression_service
        self._session_service = session_service
        self._enabled = enabled

    @property
    def name(self) -> str:
        return "pytest_compression_handler"

    @property
    def priority(self) -> int:
        # Lower priority than dangerous command handler but still high
        return 90

    async def can_handle(self, context: ToolCallContext) -> bool:
        if not self._enabled:
            return False

        tool_name: str = context.tool_name or ""
        arguments: Any = context.tool_arguments

        # Use service to detect pytest command from tool name and arguments
        try:
            result = self._service.scan_for_pytest(tool_name, arguments)
            return result is not None
        except Exception:
            logger.warning(
                "PytestCompressionHandler.can_handle failed to scan arguments",
                exc_info=True,
            )
            return False

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        tool_name: str = context.tool_name or ""
        arguments: Any = context.tool_arguments

        scan_result = self._service.scan_for_pytest(tool_name, arguments)
        if scan_result is None:
            # Not a pytest command; do not swallow
            return ToolCallReactionResult(should_swallow=False)

        is_pytest, command = scan_result

        logger.info(
            "Detected pytest command in tool call. Setting compression state for next reply. Tool='%s', Command='%s'",
            tool_name,
            command,
        )

        # Set compression state in session
        try:
            session = await self._session_service.get_session(context.session_id)
            new_state = session.state.with_compress_next_tool_call_reply(True)
            session.state = new_state
            await self._session_service.update_session(session)
            logger.info(f"Set compression state for session {context.session_id}")
        except Exception as e:
            logger.error(
                f"Failed to set compression state for session {context.session_id}: {e}"
            )

        # Do NOT swallow the tool call - let it execute normally
        # We just set the state so the reply will be compressed
        return ToolCallReactionResult(
            should_swallow=False,
            metadata={
                "handler": self.name,
                "detected_pytest": True,
                "command": command,
                "tool_name": tool_name,
                "compression_state_set": True,
                "source": "pytest_compression_detector",
            },
        )
