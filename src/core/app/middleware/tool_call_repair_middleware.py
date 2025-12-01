from __future__ import annotations

import logging
from typing import Any

from src.core.config.app_config import AppConfig
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
)
from src.core.services.tool_call_repair_service import ToolCallRepairService

logger = logging.getLogger(__name__)


class ToolCallRepairMiddleware(IResponseMiddleware):
    """
    Middleware to detect and repair tool calls embedded as text in LLM responses,
    converting them into a structured OpenAI-compatible tool_calls format.
    """

    def __init__(
        self, config: AppConfig, tool_call_repair_service: ToolCallRepairService
    ) -> None:
        self.config = config
        self.tool_call_repair_service = tool_call_repair_service

    def _extract_allowed_tools(self, request: Any) -> list[str] | None:
        """Extract allowed tool names from the request."""
        if not request:
            return None

        tools = getattr(request, "tools", None)
        if not tools:
            return None

        allowed_tools = []
        for tool in tools:
            if isinstance(tool, dict):
                func = tool.get("function")
                if isinstance(func, dict):
                    name = func.get("name")
                    if name:
                        allowed_tools.append(name)
            elif hasattr(tool, "function"):
                func = getattr(tool, "function", None)
                name = getattr(func, "name", None)
                if name:
                    allowed_tools.append(name)
        return allowed_tools

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        """
        Processes the response to detect and repair tool calls if enabled.

        NOTE: For streaming responses, tool call repair is handled by
        ToolCallRepairProcessor in the streaming pipeline. This middleware
        only processes non-streaming responses to avoid duplicate detection.
        """
        if not self.config.session.tool_call_repair_enabled:
            return response

        # Skip streaming responses - these are handled by ToolCallRepairProcessor
        # in the streaming pipeline to avoid duplicate tool call detection
        if is_streaming:
            return response

        # Only attempt repair if the content is a string
        if isinstance(response.content, str):
            allowed_tools = self._extract_allowed_tools(context.get("original_request"))
            repaired_result = self.tool_call_repair_service.repair_tool_calls(
                response.content, allowed_tools=allowed_tools
            )
            if repaired_result:
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        f"Tool call detected and repaired for session {session_id}"
                    )
                # Add tool_calls to metadata for internal processing
                if "tool_calls" not in response.metadata:
                    response.metadata["tool_calls"] = []
                response.metadata["tool_calls"].append(repaired_result.tool_call)

                # Mark as "virtual" tool calls (extracted from XML content).
                # This signals downstream serialization to strip tool_calls from
                # the response, leaving only XML content for virtual-mode clients.
                response.metadata["_virtual_tool_calls"] = True

                # Set finish_reason to "tool_calls" to signal tool call presence
                response.metadata["finish_reason"] = "tool_calls"
        return response
