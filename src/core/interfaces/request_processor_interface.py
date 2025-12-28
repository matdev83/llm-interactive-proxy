from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic.types import JsonValue

from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope


class IRequestMiddleware(ABC):
    """Interface for request middleware.

    This interface defines the contract for components that process chat requests
    before they are sent to the backend.
    """

    @abstractmethod
    async def process(
        self, request: ChatRequest, context: dict[str, JsonValue] | None = None
    ) -> ChatRequest:
        """Process a chat request.

        Args:
            request: The chat request to process
            context: Additional context (JSON-serializable values)

        Returns:
            The processed chat request
        """


class IRequestProcessor(ABC):
    """Interface for processing chat completion requests.

    This interface defines the contract for components that process incoming
    chat completion requests and produce responses, encapsulating the core
    request-response flow logic.
    """

    @abstractmethod
    async def process_request(
        self,
        context: RequestContext,
        request_data: ChatRequest,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Process an incoming chat completion request in a transport-agnostic way.

        Args:
            context: Transport-agnostic request context containing headers/cookies/state
            request_data: The parsed request data (canonical ChatRequest)

        Returns:
            Either a ResponseEnvelope for non-streaming requests or
            a StreamingResponseEnvelope for streaming requests.
        """
