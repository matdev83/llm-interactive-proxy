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
        Processes the response - now a TRANSPARENT PASS-THROUGH.

        DESIGN DECISION: Virtual tool call detection (parsing XML from message
        content) has been DISABLED because:
        1. Clients like Cline, RooCode, KiloCode parse XML tool calls themselves
        2. Attempting to detect XML causes false positives (brain_dump, memory_bank, etc.)
        3. It interferes with client-specific structured prompting
        4. Native tool_calls (already structured) are passed through unchanged

        The proxy should be TRANSPARENT - content passes through as-is.
        Tool call detection is the CLIENT's responsibility, not the proxy's.
        """
        # Simply pass through - no XML detection, no modification
        return response
