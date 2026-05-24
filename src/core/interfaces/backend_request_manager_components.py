"""
Component interfaces for backend request manager refactoring.

This module defines the interfaces for the refactored BackendRequestManager components,
enabling modular design and testability.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.domain.backend_request_manager.context_models import (
        StreamingContext,
        StructuredOutputContext,
        ToolCallRetryState,
    )
    from src.core.domain.chat import ChatRequest
    from src.core.domain.processed_result import ProcessedResult
    from src.core.domain.request_context import RequestContext
    from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
    from src.core.interfaces.loop_detector_interface import ILoopDetector
    from src.core.interfaces.response_processor_interface import ProcessedResponse
else:
    from typing import Any

    StreamingContext = dict[str, Any]


class IBackendRequestPreparation(ABC):
    """Interface for preparing backend requests from command results and compaction."""

    @abstractmethod
    async def prepare(
        self,
        request: ChatRequest,
        command_result: ProcessedResult,
        *,
        history_compaction_session_allowed: bool = True,
    ) -> ChatRequest | None:
        """Return a new request with normalized messages or None to skip backend.

        Args:
            request: The original backend request
            command_result: Result of command processing
            history_compaction_session_allowed: When False, skip history (stale tool
                output) compaction for this request even if globally enabled.

        Returns:
            A new request with normalized messages, or None to skip backend execution

        Preconditions:
            - request.messages and command_result are non-null

        Postconditions:
            - Returned request uses new message list when modified
            - Original request instance is not mutated
        """
        ...


class IToolCallRetryCoordinator(ABC):
    """Interface for coordinating tool-call retry flows with escalating steering."""

    @abstractmethod
    async def handle_non_streaming(
        self,
        request: ChatRequest,
        response: ResponseEnvelope,
        context: RequestContext | dict[str, Any],
        retry_state: ToolCallRetryState,
    ) -> ResponseEnvelope | None:
        """Return a retried response or None when no retry is needed.

        Args:
            request: The original backend request
            response: The backend response indicating a swallowed tool call
            context: Request context
            retry_state: Current retry state tracking

        Returns:
            A retried response envelope, or None if no retry is needed

        Preconditions:
            - retry_state reflects current retry count and limit

        Postconditions:
            - Retry count metadata is updated on retried responses
            - No retries beyond configured limits
        """
        ...

    @abstractmethod
    async def handle_streaming(
        self,
        request: ChatRequest,
        response: ResponseEnvelope,
        context: RequestContext | dict[str, Any],
        retry_state: ToolCallRetryState,
    ) -> StreamingResponseEnvelope | None:
        """Return a retried stream or terminal stream when needed.

        Args:
            request: The original backend request
            response: The backend response indicating a swallowed tool call
            context: Request context
            retry_state: Current retry state tracking

        Returns:
            A retried streaming response envelope, or None if no retry is needed

        Preconditions:
            - retry_state reflects current retry count and limit

        Postconditions:
            - Retry count metadata is updated on retried responses
            - No retries beyond configured limits
        """
        ...


class IStructuredOutputEnforcer(ABC):
    """Interface for applying structured output validation when schema is present."""

    @abstractmethod
    async def enforce(
        self,
        response: ProcessedResponse,
        context: StructuredOutputContext,
    ) -> ProcessedResponse:
        """Validate structured output and return a processed response.

        Args:
            response: The processed response to validate
            context: Structured output validation context

        Returns:
            A processed response with validated content

        Preconditions:
            - context.schema is present

        Postconditions:
            - Response content conforms to schema or raises validation error
        """
        ...


class ILoopDetectorFactory(ABC):
    """Interface for providing per-stream loop detector instances."""

    @abstractmethod
    def create(self) -> ILoopDetector:
        """Return a ready loop detector instance.

        Returns:
            A loop detector instance that has been reset and is ready for use
        """
        ...


class IQualityVerifierStreamVerifier(ABC):
    """Interface for buffering and verifying streaming output when Quality Verifier is enabled."""

    @abstractmethod
    def verify_or_passthrough(
        self,
        request: ChatRequest,
        stream: AsyncIterator[ProcessedResponse],
        context: StreamingContext,
        request_context: RequestContext | None = None,
    ) -> AsyncIterator[ProcessedResponse]:
        """Stream path aligned with non-streaming Quality Verifier behavior.

        On a scheduled verifier turn, the client stream is held while the verifier
        runs (plus one optional XML-format retry). The eligible-turn counter is
        reset after the episode. If the verdict is pass or unparseable, the
        original buffered stream is replayed. If the verdict is steer, an inline
        main-model recall is attempted; on recall failure the buffered original
        is replayed. Successful steering does not enqueue next-request-only notes.

        Args:
            request: The original backend request
            stream: The streaming response chunks
            context: Streaming context with session_id, stream_id, etc.
            request_context: Request context for cancellation gate resolution (optional)

        Returns:
            An async iterator of processed response chunks (verified, recalled, or original)

        Preconditions:
            - Stream yields ProcessedResponse instances

        Postconditions:
            - Output stream preserves metadata contracts
        """
        ...
