"""Steering policy for cat-based file creation / append via shell redirection."""

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

DEFAULT_STEERING_MESSAGE: Final[str] = (
    "You should never try to use `cat` command to append or to edit files. "
    "Use proper tools provided by the user's agent app for file editing."
)

# Append first: `\bcat\s+>` would match the first `>` in `cat >>`.
_CAT_APPEND_RE = re.compile(r"\bcat\s+>>", re.IGNORECASE)
_CAT_OVERWRITE_RE = re.compile(r"\bcat\s+>", re.IGNORECASE)


class CatFileEditsSteeringPolicy(ISteeringPolicy):
    """Blocks shell commands that use cat with output redirection to create/append files."""

    def __init__(
        self,
        message: str | None = None,
        enabled: bool = False,
        prompt_override_path: Path | None = None,
        command_service: CommandExtractionService | None = None,
    ) -> None:
        self._enabled = enabled
        self._command_service = command_service or CommandExtractionService()
        self._shell_tools = set(ShellExecutionTools.get_all())

        final_message = message or DEFAULT_STEERING_MESSAGE
        if prompt_override_path and prompt_override_path.is_file():
            try:
                final_message = prompt_override_path.read_text(encoding="utf-8")
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Loaded cat file edits steering prompt from %s",
                        prompt_override_path,
                    )
            except OSError as e:
                logger.warning(
                    "Failed to read cat file edits steering prompt from %s: %s. Using default.",
                    prompt_override_path,
                    e,
                    exc_info=True,
                )
        self._message = final_message

    @property
    def name(self) -> str:
        return "cat_file_edits"

    @property
    def priority(self) -> int:
        # After inline_python / pytest_full_suite (95), before binary_file_edit (90).
        return 93

    def _redirection_variant(self, command: str) -> str | None:
        if _CAT_APPEND_RE.search(command):
            return "append"
        if _CAT_OVERWRITE_RE.search(command):
            return "overwrite"
        return None

    async def evaluate(
        self, context: ToolCallContext, command: str, dry_run: bool = False
    ) -> SteeringResult | None:
        if not self._enabled:
            return None

        tool_name = (context.tool_name or "").strip()

        if (
            tool_name not in self._shell_tools
            and not self._command_service.is_shell_tool(tool_name)
        ):
            return None

        if not command:
            return None

        variant = self._redirection_variant(command)
        if not variant:
            return None

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Steering cat file redirection in session %s (%s)",
                context.session_id,
                variant,
            )

        return SteeringResult(
            message=self._message,
            should_block=True,
            policy_name=self.name,
            severity="warning",
            metadata={
                "tool_name": context.tool_name,
                "command_preview": command[:200],
                "cat_redirection": variant,
                "source": "cat_file_edits_steering",
            },
        )


__all__ = ["CatFileEditsSteeringPolicy"]
