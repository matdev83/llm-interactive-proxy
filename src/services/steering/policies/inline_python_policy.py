"""Inline Python execution steering policy."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Final

from src.core.domain.tool_constants import ShellExecutionTools
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.core.services.command_extraction_service import CommandExtractionService

from ..interfaces import ISteeringPolicy
from ..models import SteeringResult

logger = logging.getLogger(__name__)


class InlinePythonPolicy(ISteeringPolicy):
    """Policy that blocks inline Python execution attempts (python -c)."""

    DEFAULT_MESSAGE: Final[str] = (
        "You were trying to use inline Python code. It tends to break terminals "
        "and is generally unstable. Please create a temporary script and run it instead"
    )

    # Matches `python -c` or `python.exe -c` with optional flags/args
    _INLINE_PYTHON_PATTERN = re.compile(
        r"(?:^|[;&|\s])python(?:3|[\d\.]*)?(?:\.exe)?\s+(?:-[a-zA-Z0-9]+\s+)*-c\s+",
        re.IGNORECASE,
    )

    def __init__(
        self,
        message: str | None = None,
        enabled: bool = True,
        prompt_override_path: Path | None = None,
        command_service: CommandExtractionService | None = None,
    ) -> None:
        """Initialize the policy.

        Args:
            message: Custom steering message
            enabled: Whether the policy is enabled
            prompt_override_path: Path to a file to override the default message
            command_service: Service for command extraction (for DI)
        """
        self._enabled = enabled
        self._command_service = command_service or CommandExtractionService()
        self._shell_tools = set(ShellExecutionTools.get_all())

        final_message = message or self.DEFAULT_MESSAGE
        if prompt_override_path and prompt_override_path.is_file():
            try:
                final_message = prompt_override_path.read_text(encoding="utf-8")
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Loaded inline python steering prompt from %s",
                        prompt_override_path,
                    )
            except Exception:
                logger.warning(
                    "Failed to read inline python steering prompt from %s, using default.",
                    prompt_override_path,
                    exc_info=True,
                )
        self._message = final_message

    @property
    def name(self) -> str:
        return "inline_python"

    @property
    def priority(self) -> int:
        # High priority to catch before general execution
        return 95

    async def evaluate(
        self, context: ToolCallContext, command: str, dry_run: bool = False
    ) -> SteeringResult | None:
        """Evaluate if command contains inline Python execution."""
        if not self._enabled:
            return None

        tool_name = (context.tool_name or "").strip()

        # Check if tool is a shell execution tool
        if (
            tool_name not in self._shell_tools
            and not self._command_service.is_shell_tool(tool_name)
        ):
            return None

        if not command:
            return None

        # Check for inline python pattern
        if not self._INLINE_PYTHON_PATTERN.search(command):
            return None

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Intercepted inline Python execution attempt in session %s",
                context.session_id,
            )

        return SteeringResult(
            message=self._message,
            should_block=True,
            policy_name=self.name,
            severity="warning",
            metadata={
                "tool_name": context.tool_name,
                "command_preview": command[:200],
                "source": "inline_python_steering",
            },
        )


__all__ = ["InlinePythonPolicy"]
