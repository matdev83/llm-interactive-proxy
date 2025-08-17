"""
Chat Controller

Handles all chat completion related API endpoints.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Body, HTTPException, Request, Response
from pydantic import BaseModel

from src.core.common.exceptions import LoopDetectionError
from src.core.interfaces.di import IServiceProvider
from src.core.interfaces.request_processor import IRequestProcessor

logger = logging.getLogger(__name__)


class ChatCompletionRequest(BaseModel):
    """Chat completion request model."""

    model: str
    messages: list[dict[str, Any]]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: dict[str, Any] | None = None
    user: str | None = None
    session_id: str | None = None


class ChatController:
    """Controller for chat-related endpoints."""

    def __init__(self, request_processor: IRequestProcessor):
        """Initialize the controller.

        Args:
            request_processor: The request processor service
        """
        self._processor = request_processor

    async def handle_chat_completion(
        self, request: Request, request_data: ChatCompletionRequest
    ) -> Response:
        """Handle chat completion requests.

        Args:
            request: The HTTP request
            request_data: The parsed request data

        Returns:
            An HTTP response
        """
        logger.info(f"Handling chat completion request: model={request_data.model}")

        try:
            # Process the request using the request processor
            return await self._processor.process_request(request, request_data)
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except LoopDetectionError as e:
            # Re-raise LoopDetectionError directly so it can be handled by proxy_exception_handler
            raise e
        except Exception as e:
            logger.error(f"Error handling chat completion: {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail={"error": str(e), "type": "ChatCompletionError"}
            )

    async def handle_legacy_compatibility(
        self, request: Request, request_data: dict[str, Any] = Body(...)
    ) -> Response:
        """Handle legacy format requests.

        Args:
            request: The HTTP request
            request_data: The raw request data

        Returns:
            An HTTP response
        """
        try:
            # Convert legacy format to our model
            # This is a simplified implementation - in reality we'd handle more formats
            request_model = ChatCompletionRequest(
                model=request_data.get("model", "unknown"),
                messages=request_data.get("messages", []),
                stream=request_data.get("stream", False),
                temperature=request_data.get("temperature"),
                max_tokens=request_data.get("max_tokens"),
                tools=request_data.get("tools"),
                tool_choice=request_data.get("tool_choice"),
                user=request_data.get("user"),
                session_id=request_data.get("session_id"),
            )

            # Process using standard handler
            return await self.handle_chat_completion(request, request_model)
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            logger.error(f"Error handling legacy request: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={"error": str(e), "type": "LegacyCompatibilityError"},
            )


def get_chat_controller(service_provider: IServiceProvider) -> ChatController:
    """Create a chat controller using the service provider.

    Args:
        service_provider: The service provider to use

    Returns:
        A configured chat controller
    """
    request_processor = service_provider.get_required_service(IRequestProcessor)  # type: ignore
    return ChatController(request_processor)
