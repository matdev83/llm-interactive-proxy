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
        ResponseProcessingContext,
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
    ) -> ChatRequest | None:
        """Return a new request with normalized messages or None to skip backend.

        Args:
            request: The original backend request
            command_result: Result of command processing

        Returns:
            A new request with normalized messages, or None to skip backend execution

        Preconditions:
            - request.messages and command_result are non-null

        Postconditions:
            - Returned request uses new message list when modified
            - Original request instance is not mutated
        """
        ...


class INonStreamingBackendResponseHandler(ABC):
    """Interface for processing non-streaming backend responses."""

    @abstractmethod
    async def handle(
        self,
        response: ResponseEnvelope,
        request: ChatRequest,
        context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> ResponseEnvelope:
        """Return a processed non-streaming response envelope.

        Args:
            response: The backend response envelope
            request: The original backend request
            context: Request context
            processing_context: Typed processing context

        Returns:
            A processed response envelope with normalized content and metadata

        Preconditions:
            - response.content is available for non-streaming requests

        Postconditions:
            - Response content and metadata are normalized and safe to serialize
            - No additional backend calls beyond retry policy
        """
        ...


class IStreamingBackendResponseHandler(ABC):
    """Interface for handling streaming backend responses."""

    @abstractmethod
    async def handle(
        self,
        stream: StreamingResponseEnvelope,
        request: ChatRequest,
        context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> StreamingResponseEnvelope:
        """Return a processed streaming response envelope.

        Args:
            stream: The streaming response envelope
            request: The original backend request
            context: Request context
            processing_context: Typed processing context

        Returns:
            A processed streaming response envelope with middleware applied

        Preconditions:
            - Input is a streaming request and a streaming envelope

        Postconditions:
            - Stream yields processed chunks with required metadata
            - Preserve media_type, headers, and cancel_callback
        """
        ...


class IToolCallRetryCoordinator(ABC):
    """Interface for coordinating tool-call retry flows with escalating steering."""

    @abstractmethod
    async def handle_non_streaming(
        self,
        request: ChatRequest,
        response: ResponseEnvelope,
        context: RequestContext,
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
        context: RequestContext,
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


class IAngelStreamVerifier(ABC):
    """Interface for buffering and verifying streaming output when Angel is enabled."""

    @abstractmethod
    def verify_or_passthrough(
        self,
        request: ChatRequest,
        stream: AsyncIterator[ProcessedResponse],
        context: StreamingContext,
    ) -> AsyncIterator[ProcessedResponse]:
        """Return verified stream or original stream when no steering is needed.

        Args:
            request: The original backend request
            stream: The streaming response chunks
            context: Streaming context with session_id, stream_id, etc.

        Returns:
            An async iterator of processed response chunks (verified or original)

        Preconditions:
            - Stream yields ProcessedResponse instances

        Postconditions:
            - Output stream preserves metadata contracts
        """
        ...
