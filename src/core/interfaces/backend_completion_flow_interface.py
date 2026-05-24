"""Interface for backend completion flow orchestration."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope


class IBackendCompletionFlow(ABC):
    """Interface for completion orchestration flow.

    This interface defines the contract for orchestrating backend completion
    requests, including failover, retry, wire capture, and usage tracking.
    """

    @abstractmethod
    async def call_completion(
        self,
        request: ChatRequest,
        stream: bool = False,
        allow_failover: bool = True,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute completion orchestration.

        Args:
            request: The chat completion request
            stream: Whether to stream the response
            allow_failover: Whether to allow failover to alternative backends
            context: Optional request context for tracking and metadata

        Returns:
            Either a complete response or a streaming response envelope

        Raises:
            BackendError: If the completion request fails
        """
