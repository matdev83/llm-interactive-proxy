"""Interface for cross-request tool-progress loop detection."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.chat import ChatRequest
from src.core.domain.tool_progress_loop import ToolProgressLoopDecision


class IToolProgressLoopGuard(ABC):
    """Evaluates session-level tool progress before another backend dispatch."""

    @abstractmethod
    async def evaluate_request(
        self,
        *,
        session_id: str,
        request: ChatRequest,
    ) -> ToolProgressLoopDecision:
        """Return whether the request should continue to backend execution."""
