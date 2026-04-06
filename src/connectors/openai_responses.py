from __future__ import annotations

from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.openai import OpenAIConnector
from src.core.common.exceptions import InvalidRequestError
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.services.backend_registry import backend_registry


class OpenAIResponsesConnector(OpenAIConnector):
    """OpenAI Responses API connector that extends the base OpenAI connector.

    This connector specifically handles the OpenAI Responses API endpoint (/v1/responses)
    for structured output generation with JSON schema validation.
    """

    backend_type: str = "openai-responses"

    async def chat_completions(  # type: ignore[override]
        self,
        request: ConnectorChatCompletionsRequest,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Route canonical chat completions to the Responses API implementation."""
        if not isinstance(request, ConnectorChatCompletionsRequest):
            raise InvalidRequestError(
                message=(
                    "OpenAIResponsesConnector.chat_completions requires "
                    "ConnectorChatCompletionsRequest."
                ),
                details={
                    "received_type": type(request).__name__,
                    "connector": "openai-responses",
                },
            )
        if (
            request.cancellation_coordinator is not None
            and request.cancellation_token is not None
        ):
            request.cancellation_coordinator.ensure_not_cancelled(
                request.cancellation_token
            )
        options = dict(request.options) if request.options else {}
        return await self.responses(
            request.request,
            list(request.processed_messages),
            request.effective_model,
            request.identity,
            **options,
        )


# Register the OpenAI Responses API backend
backend_registry.register_backend("openai-responses", OpenAIResponsesConnector)
