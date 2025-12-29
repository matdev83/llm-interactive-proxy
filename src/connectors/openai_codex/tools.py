"""Tool execution service for OpenAI Codex connector.

This service handles execution of proxy tools and MCP tools with consistent
result formatting and error handling.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from src.connectors._openai_codex_compatibility_errors import (
    CompatibilityErrorCode,
    TranslationError,
)
from src.connectors.openai_codex.contracts import ToolArguments, ToolExecutionResult
from src.connectors.openai_codex.interfaces import IToolExecutionService
from src.core.services.universal_mcp_client import OpenAIFunctionSchema
from src.core.services.universal_tool_executor import UniversalToolExecutor

logger = logging.getLogger(__name__)


class ToolExecutionService(IToolExecutionService):
    """Service for executing proxy and MCP tools with formatted results.

    This service handles:
    - Conversation control tools (attempt_completion, ask_followup_question)
    - Proxy tools via UniversalToolExecutor
    - MCP tools via MCP client bridge
    - Result formatting using KiloToolTranslator
    """

    def __init__(
        self,
        universal_executor: UniversalToolExecutor | None = None,
        kilo_translator: Any | None = None,
        mcp_client: Any | None = None,
    ) -> None:
        """Initialize the tool execution service.

        Args:
            universal_executor: UniversalToolExecutor instance for proxy tools
            kilo_translator: KiloToolTranslator instance for result formatting
            mcp_client: MCP client instance for MCP tool execution
        """
        self._universal_executor = universal_executor
        self._kilo_translator = kilo_translator
        self._mcp_client = mcp_client

    def _get_universal_executor(self) -> UniversalToolExecutor:
        """Get or create the universal tool executor."""
        if self._universal_executor is None:
            # Initialize with current working directory
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
        # Handle conversation control tools specially
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

        # Execute other proxy tools via UniversalToolExecutor
        executor = self._get_universal_executor()

        try:
            # Remove __proxy_ prefix for execution
            actual_tool_name = tool_name.replace("__proxy_", "")

            # Execute the tool
            exec_result = await executor.execute_tool(
                actual_tool_name, arguments.payload
            )

            # Format result using KiloToolTranslator if available
            if self._kilo_translator:
                formatted_result = self._kilo_translator.format_tool_result(
                    actual_tool_name, exec_result
                )
                return ToolExecutionResult(
                    success=True,
                    result=formatted_result,
                    error=None,
                )
            else:
                # Fallback to string representation if no translator
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

    async def execute_mcp_tool(
        self, tool_name: str, arguments: ToolArguments, session_id: str | None = None
    ) -> ToolExecutionResult:
        """Execute an MCP tool and return formatted result.

        Args:
            tool_name: Name of the MCP tool wrapper (typically __proxy_use_mcp_tool)
            arguments: Tool arguments containing tool_name and tool_arguments
            session_id: Optional session ID for telemetry

        Returns:
            Tool execution result with success/error status
        """
        start_time = time.time()
        original_xml = arguments.payload.get("original_xml")
        original_xml_text = original_xml if isinstance(original_xml, str) else None

        # Extract MCP tool name from arguments
        mcp_tool_name = arguments.payload.get("tool_name", "")
        if not mcp_tool_name or not isinstance(mcp_tool_name, str):
            error = TranslationError(
                message="Missing or invalid 'tool_name' parameter in MCP tool invocation",
                tool_name=tool_name,
                error_code=CompatibilityErrorCode.INVALID_TOOL_ARGUMENTS,
                session_id=session_id,
                details={"missing_parameters": ["tool_name"]},
            )
            logger.error("MCP tool execution error: %s", error, exc_info=True)
            return ToolExecutionResult(
                success=False,
                result="",
                error=str(error),
            )

        # Extract MCP tool parameters
        mcp_parameters = arguments.payload.get("tool_arguments", {})
        if not isinstance(mcp_parameters, dict):
            mcp_parameters = {}

        # Check if MCP client is available
        if not self._mcp_client:
            error = TranslationError(
                message="MCP server not available",
                tool_name=mcp_tool_name,
                error_code=CompatibilityErrorCode.MCP_UNAVAILABLE,
                session_id=session_id,
            )
            logger.error("MCP tool execution error: %s", error, exc_info=True)
            return ToolExecutionResult(
                success=False,
                result="",
                error=str(error),
            )

        try:
            # Connect to MCP server if not already connected
            try:
                if (
                    hasattr(self._mcp_client, "is_connected")
                    and not self._mcp_client.is_connected()
                ):
                    logger.info("MCP client not connected, attempting to connect...")
                    if hasattr(self._mcp_client, "connect"):
                        await self._mcp_client.connect()
                        logger.info("Successfully connected to MCP server")
            except Exception as conn_error:
                logger.error(
                    "Failed to connect to MCP server: %s",
                    str(conn_error),
                    exc_info=True,
                )
                error = TranslationError(
                    message=f"Failed to connect to MCP server: {conn_error!s}",
                    tool_name=mcp_tool_name,
                    error_code=CompatibilityErrorCode.MCP_UNAVAILABLE,
                    session_id=session_id,
                    details={"connection_error": str(conn_error)},
                )
                logger.error("MCP tool execution error: %s", error, exc_info=True)
                return ToolExecutionResult(
                    success=False,
                    result="",
                    error=str(error),
                )

            # Translate parameters if needed (schema translation)
            if self._kilo_translator and hasattr(
                self._kilo_translator, "_translate_mcp_parameters"
            ):
                # Get MCP tool schema if available
                mcp_schema = None
                if hasattr(self._mcp_client, "get_tool_schema"):
                    try:
                        mcp_schema = await self._mcp_client.get_tool_schema(
                            mcp_tool_name
                        )
                    except Exception as e:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Could not retrieve MCP tool schema: %s",
                                e,
                                exc_info=True,
                            )

                # Translate parameters
                if mcp_schema:
                    try:
                        mcp_parameters = (
                            self._kilo_translator._translate_mcp_parameters(
                                mcp_parameters, mcp_schema
                            )
                        )
                    except Exception as e:
                        logger.warning(
                            "Parameter translation failed, using original parameters: %s",
                            str(e),
                            exc_info=True,
                        )

            # Execute MCP tool with timeout
            try:
                mcp_result = await asyncio.wait_for(
                    self._mcp_client.call_tool(mcp_tool_name, mcp_parameters),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                error = TranslationError(
                    message="Execution timed out after 30s",
                    tool_name=mcp_tool_name,
                    error_code=CompatibilityErrorCode.MCP_TIMEOUT,
                    session_id=session_id,
                )
                logger.error("MCP tool execution error: %s", error, exc_info=True)
                return ToolExecutionResult(
                    success=False,
                    result="",
                    error=str(error),
                )
            except AttributeError as e:
                # MCP tool not found
                error = TranslationError(
                    message=f"Tool {mcp_tool_name} not found",
                    tool_name=mcp_tool_name,
                    error_code=CompatibilityErrorCode.MCP_TOOL_NOT_FOUND,
                    session_id=session_id,
                    details={"mcp_error": str(e)},
                )
                logger.error("MCP tool execution error: %s", error, exc_info=True)
                return ToolExecutionResult(
                    success=False,
                    result="",
                    error=str(error),
                )

            # Log MCP response received
            logger.debug(
                "Received MCP tool response: tool=%s, result_type=%s",
                mcp_tool_name,
                type(mcp_result).__name__,
            )

            # Format MCP result for KiloCode
            if self._kilo_translator:
                formatted_result = self._kilo_translator.format_tool_result(
                    mcp_tool_name, mcp_result
                )
                result = ToolExecutionResult(
                    success=True,
                    result=formatted_result,
                    error=None,
                )
            else:
                # Fallback to string representation if no translator
                result = ToolExecutionResult(
                    success=True,
                    result=str(mcp_result),
                    error=None,
                )

        except TranslationError as e:
            # Log error with telemetry
            logger.error(
                "MCP tool execution failed [%s]: %s (tool: %s, session: %s)",
                e.error_code,
                str(e),
                mcp_tool_name,
                session_id,
                exc_info=True,
            )

            # Track error in telemetry
            try:
                from src.connectors._openai_codex_telemetry import get_telemetry

                telemetry = get_telemetry()
                if telemetry:
                    duration_ms = (time.time() - start_time) * 1000
                    telemetry.log_error_event(
                        session_id=session_id or "unknown",
                        error_code=str(e.error_code),
                        tool_name=mcp_tool_name,
                        error_message=str(e),
                        original_xml=original_xml_text,
                        stack_trace="",
                    )
            except ImportError:
                pass

            return ToolExecutionResult(
                success=False,
                result=f"[{mcp_tool_name}] Error: {e!s}",
                error=str(e),
            )

        except Exception as e:
            # Unexpected error
            logger.error(
                "Unexpected error during MCP tool execution: %s (tool: %s, session: %s)",
                str(e),
                mcp_tool_name,
                session_id,
                exc_info=True,
            )
            return ToolExecutionResult(
                success=False,
                result=f"[{mcp_tool_name}] Error: {e!s}",
                error=str(e),
            )

        # Track execution duration for telemetry
        duration_ms = (time.time() - start_time) * 1000
        logger.debug(
            "MCP tool %s executed in %.2fms (success: %s)",
            mcp_tool_name,
            duration_ms,
            result.success,
        )

        # Log MCP tool execution end event
        try:
            from src.connectors._openai_codex_telemetry import get_telemetry

            telemetry = get_telemetry()
            if telemetry and result.success:
                telemetry.log_translation_event(
                    session_id=session_id or "unknown",
                    tool_name=mcp_tool_name,
                    original_xml=original_xml_text,
                    translated_tool=mcp_tool_name,
                    execution_mode="mcp",
                    duration_ms=duration_ms,
                    success=True,
                )
        except ImportError:
            pass

        return result

    def get_available_tool_schemas(self) -> list[OpenAIFunctionSchema]:
        """Get schemas for all available tools (proxy + MCP).

        Returns:
            List of OpenAI function schemas
        """
        executor = self._get_universal_executor()
        return executor.get_tool_schemas()

    async def connect_mcp_server(
        self, server_name: str, server_config: dict[str, Any]
    ) -> bool:
        """Connect to an MCP server to make its tools available.

        Args:
            server_name: Unique name for the server
            server_config: Server configuration

        Returns:
            True if connection successful, False otherwise
        """
        executor = self._get_universal_executor()
        return await executor.connect_mcp_server(server_name, server_config)
