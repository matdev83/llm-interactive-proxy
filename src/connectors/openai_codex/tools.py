"""Tool execution service for OpenAI Codex connector.

Executes proxy-side tools with consistent result formatting. MCP is not run
in the proxy; configure MCP in the upstream agent (Codex, ACP, etc.).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from src.connectors.openai_codex.contracts import ToolArguments, ToolExecutionResult
from src.connectors.openai_codex.interfaces import IToolExecutionService
from src.core.domain.openai_function_schema import OpenAIFunctionSchema
from src.core.services.universal_tool_executor import UniversalToolExecutor

logger = logging.getLogger(__name__)


class ToolExecutionService(IToolExecutionService):
    """Service for executing proxy tools with formatted results.

    Handles conversation control tools (attempt_completion, ask_followup_question),
    other proxy tools via UniversalToolExecutor, and optional KiloToolTranslator
    formatting.
    """

    def __init__(
        self,
        universal_executor: UniversalToolExecutor | None = None,
        kilo_translator: Any | None = None,
    ) -> None:
        self._universal_executor = universal_executor
        self._kilo_translator = kilo_translator

    def _get_universal_executor(self) -> UniversalToolExecutor:
        """Get or create the universal tool executor."""
        if self._universal_executor is None:
            working_dir = os.getcwd()
            self._universal_executor = UniversalToolExecutor(
                working_directory=working_dir
            )
        return self._universal_executor

    async def execute_proxy_tool(
        self, tool_name: str, arguments: ToolArguments, session_id: str | None = None
    ) -> ToolExecutionResult:
        """Execute a proxy tool and return formatted result.

        Args:
            tool_name: Name of the tool to execute (may include __proxy_ prefix)
            arguments: Tool arguments
            session_id: Optional session ID for telemetry and conversation control

        Returns:
            Tool execution result with success/error status
        """
        if tool_name in ("__proxy_attempt_completion", "__proxy_ask_followup_question"):
            if not self._kilo_translator:
                return ToolExecutionResult(
                    success=False,
                    result="",
                    error="KiloToolTranslator not available",
                )

            try:
                formatted_result = (
                    await self._kilo_translator.handle_conversation_control(
                        tool_name, arguments.payload, session_id
                    )
                )
                return ToolExecutionResult(
                    success=True,
                    result=formatted_result,
                    error=None,
                )
            except Exception as e:
                logger.error(
                    "Conversation control tool execution failed for %s: %s",
                    tool_name,
                    str(e),
                    exc_info=True,
                )
                return ToolExecutionResult(
                    success=False,
                    result=f"[{tool_name.replace('__proxy_', '')}] Error: {e!s}",
                    error=str(e),
                )

        executor = self._get_universal_executor()

        try:
            actual_tool_name = tool_name.replace("__proxy_", "")

            exec_result = await executor.execute_tool(
                actual_tool_name, arguments.payload
            )

            if self._kilo_translator:
                formatted_result = self._kilo_translator.format_tool_result(
                    actual_tool_name, exec_result
                )
                return ToolExecutionResult(
                    success=True,
                    result=formatted_result,
                    error=None,
                )
            return ToolExecutionResult(
                success=True,
                result=str(exec_result),
                error=None,
            )

        except Exception as e:
            logger.error(
                "Proxy tool execution failed for %s: %s",
                tool_name,
                str(e),
                exc_info=True,
            )
            actual_tool_name = tool_name.replace("__proxy_", "")
            return ToolExecutionResult(
                success=False,
                result=f"[{actual_tool_name}] Error: {e!s}",
                error=str(e),
            )

    def get_available_tool_schemas(self) -> list[OpenAIFunctionSchema]:
        """Return advertised tool schemas from the universal executor (often empty)."""
        executor = self._get_universal_executor()
        return executor.get_tool_schemas()
