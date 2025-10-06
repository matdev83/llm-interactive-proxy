"""Deprecated: superseded by reactor-based approach for planning-phase counters.

This module remains only for backward compatibility in imports. Do not use.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.domain.chat import ChatRequest
from src.core.interfaces.session_service_interface import ISessionService

logger = logging.getLogger(__name__)


class PlanningPhaseMiddleware:
    """No-op placeholder. Use reactor-based counters instead."""

    def __init__(self, session_service: ISessionService) -> None:
        """Initialize the planning phase middleware.

        Args:
            session_service: Service for managing sessions
        """
        self._session_service = session_service

    async def process_request(
        self, request: ChatRequest, session_id: str, default_backend: str = "openai"
    ) -> ChatRequest:
        return request

    async def on_request_complete(
        self, session_id: str, tool_calls: list[dict[str, Any]] | None = None
    ) -> None:
        """Update planning phase counters after a request completes.

        Args:
            session_id: The session ID
            tool_calls: Optional list of tool calls from the response
        """
        return None

    def _count_file_writes(self, tool_calls: list[dict[str, Any]] | None) -> int:
        """Count the number of file write tool calls.

        Args:
            tool_calls: List of tool calls to analyze

        Returns:
            Number of file write operations detected
        """
        return 0
