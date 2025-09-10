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
        """
        if not self.config.session.tool_call_repair_enabled:
            return response

        # Only attempt repair if the content is a string
        if isinstance(response.content, str):
            repaired_tool_call = self.tool_call_repair_service.repair_tool_calls(
                response.content
            )
            if repaired_tool_call:
                logger.info(f"Tool call detected and repaired for session {session_id}")
                # Update the processed response to reflect the repaired tool call
                # and clear the original string content.
                response.content = None
                # Add tool_calls to metadata, assuming it's a list
                if "tool_calls" not in response.metadata:
                    response.metadata["tool_calls"] = []
                response.metadata["tool_calls"].append(repaired_tool_call)

                # Set finish_reason if not already set (e.g., by backend)
                if "finish_reason" not in response.metadata:
                    response.metadata["finish_reason"] = "tool_calls"
        return response
