"""Universal tool command handler for dynamic tool execution."""

from __future__ import annotations

import logging
from typing import Any

from src.core.commands.handler import ICommandHandler
from src.core.commands.models import Command
from src.core.domain.command_results import CommandResult
from src.core.commands.registry import command
from src.core.domain.command_context import CommandContext
from src.core.services.universal_tool_executor import UniversalToolExecutor

logger = logging.getLogger(__name__)


class UniversalToolHandler(ICommandHandler):
    """Universal command handler that can execute any tool dynamically."""

    def __init__(self) -> None:
        self._executor: UniversalToolExecutor | None = None

    def _get_executor(self, context: CommandContext) -> UniversalToolExecutor:
        """Get or create the universal tool executor."""
        if self._executor is None:
            # Initialize with current working directory
            import os
            working_dir = os.getcwd()
            self._executor = UniversalToolExecutor(working_directory=working_dir)
        return self._executor

    async def handle(self, command: Command, context: CommandContext) -> CommandResult:
        """Handle any tool command using the universal executor."""
        try:
            executor = self._get_executor(context)
            
            # Execute the tool
            result = await executor.execute_tool(command.name, command.arguments)
            
            # Convert to CommandResult
            return CommandResult(
                output=result.get("output", ""),
                exit_code=result.get("exit_code", 0),
                metadata=result
            )
            
        except Exception as e:
            logger.error(f"Error executing universal tool {command.name}: {e}", exc_info=True)
            return CommandResult(
                output=f"Error executing {command.name}: {str(e)}",
                exit_code=1,
                metadata={"error": str(e)}
            )


# Register handlers for all KiloCode tools
@command("read_file")
class ReadFileHandler(UniversalToolHandler):
    """Handler for read_file tool."""
    pass


@command("list_dir")
class ListDirHandler(UniversalToolHandler):
    """Handler for list_dir tool."""
    pass


@command("list_files")
class ListFilesHandler(UniversalToolHandler):
    """Handler for list_files tool (alias for list_dir)."""
    pass


@command("grep_files")
class GrepFilesHandler(UniversalToolHandler):
    """Handler for grep_files tool."""
    pass


@command("codebase_search")
class CodebaseSearchHandler(UniversalToolHandler):
    """Handler for codebase_search tool (alias for grep_files)."""
    pass


@command("search_files")
class SearchFilesHandler(UniversalToolHandler):
    """Handler for search_files tool (alias for grep_files)."""
    pass


@command("use_mcp_tool")
class UseMcpToolHandler(UniversalToolHandler):
    """Handler for use_mcp_tool (generic MCP tool execution)."""
    pass


@command("completion_marker")
class CompletionMarkerHandler(UniversalToolHandler):
    """Handler for completion_marker tool."""
    pass


@command("attempt_completion")
class AttemptCompletionHandler(UniversalToolHandler):
    """Handler for attempt_completion tool (alias for completion_marker)."""
    pass


@command("followup_marker")
class FollowupMarkerHandler(UniversalToolHandler):
    """Handler for followup_marker tool."""
    pass


@command("ask_followup_question")
class AskFollowupQuestionHandler(UniversalToolHandler):
    """Handler for ask_followup_question tool (alias for followup_marker)."""
    pass