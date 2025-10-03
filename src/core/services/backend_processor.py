"""
Backend processor implementation.

This module provides the implementation of the backend processor interface.
"""

from __future__ import annotations

# type: ignore[unreachable]
import logging
from typing import Any

from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session import SessionInteraction
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.session_service_interface import ISessionService

logger = logging.getLogger(__name__)


class BackendProcessor(IBackendProcessor):
    """Implementation of the backend processor interface."""

    def __init__(
        self,
        backend_service: IBackendService,
        session_service: ISessionService,
        application_state: IApplicationState,
    ) -> None:
        """Initialize the backend processor.

        Args:
            backend_service: The backend service to use for processing requests
            session_service: The session service to use for managing sessions
        """
        self._backend_service = backend_service
        self._session_service = session_service
        self._app_state: IApplicationState = application_state

    async def process_backend_request(
        self,
        request: ChatRequest,
        session_id: str,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Process a request through the backend service.

        Args:
            request: The request to process
            session_id: The session ID
            context: Optional request context

        Returns:
            The response from the backend
        """
        # Get the session
        session = await self._session_service.get_session(session_id)

        # Extract raw prompt content for session tracking
        raw_prompt = self._extract_raw_prompt(request.messages)

        try:
            # Include any app-level failover routes if available
            extra_body_dict = {}
            if hasattr(request, "model_dump"):
                extra_body_dict = request.model_dump()
            elif isinstance(request, dict):  # type: ignore[unreachable]  # type: ignore[unreachable]
                extra_body_dict = request  # type: ignore[unreachable]
            else:
                # Best effort conversion
                extra_body_dict = {
                    k: v
                    for k, v in request.__dict__.items()
                    if not k.startswith("_") and not callable(v)
                }

            # Get failover routes from session and add them to extra_body
            failover_routes: list[dict[str, Any]] | None = None
            if context:
                # Always use injected application state
                failover_routes = self._app_state.get_failover_routes()
            elif hasattr(session.state.backend_config, "failover_routes"):  # type: ignore[unreachable]
                _failover_routes = session.state.backend_config.failover_routes
                if isinstance(_failover_routes, list):  # type: ignore[unreachable]
                    failover_routes = _failover_routes  # type: ignore[unreachable]

            if failover_routes:
                extra_body_dict["failover_routes"] = failover_routes

            # Call the backend
            backend_response = await self._backend_service.call_completion(
                request=ChatRequest(
                    model=request.model,
                    messages=request.messages,
                    temperature=request.temperature,
                    top_p=request.top_p,
                    max_tokens=request.max_tokens,
                    stream=request.stream,
                    extra_body=extra_body_dict,
                ),
                stream=request.stream if request.stream is not None else False,
                context=context,
            )

            # Add session interaction for the request
            session.add_interaction(
                SessionInteraction(
                    prompt=raw_prompt,
                    handler="backend",
                    backend=getattr(session.state.backend_config, "backend_type", None),
                    model=getattr(session.state.backend_config, "model", None),
                    project=getattr(session.state, "project", None),
                    parameters={
                        "temperature": request.temperature,
                        "top_p": request.top_p,
                        "max_tokens": request.max_tokens,
                    },
                )
            )

            return backend_response

        except Exception as e:  # Catch all exceptions to record them in the session
            # Add a failed interaction to the session
            session.add_interaction(
                SessionInteraction(
                    prompt=raw_prompt,
                    handler="backend",
                    backend=getattr(session.state.backend_config, "backend_type", None),
                    model=getattr(session.state.backend_config, "model", None),
                    project=getattr(session.state, "project", None),
                    response=str(e),
                )
            )
            # Re-raise the exception
            raise  # Re-raise the original exception after logging

    def _extract_raw_prompt(self, messages: list[Any]) -> str:
        """Extract the raw prompt from a list of messages.

        Args:
            messages: The list of messages

        Returns:
            The raw prompt text
        """
        if not messages:
            return ""

        # Get the last user message
        for message in reversed(messages):
            role = (
                message.get("role")
                if isinstance(message, dict)
                else getattr(message, "role", None)
            )
            if role == "user":
                content_value = (
                    message.get("content")
                    if isinstance(message, dict)
                    else getattr(message, "content", None)
                )
                if isinstance(content_value, str):
                    return content_value
                elif isinstance(content_value, list):
                    # Handle multimodal content by converting to string
                    return self._convert_content_to_str(content_value)
                elif content_value is None:
                    return ""  # Explicitly handle None
                else:
                    logger.warning(
                        f"Unexpected content type in _extract_raw_prompt: {type(content_value)}"
                    )
                    return str(content_value)  # Fallback for unexpected types

        # If no user message found, return empty string
        return ""

    def _convert_content_to_str(self, content_parts: list[Any]) -> str:
        """Converts a list of content parts to a single string."""
        text_content = []
        for part in content_parts:
            if isinstance(part, dict) and part.get("type") == "text":
                text_content.append(part.get("text", ""))
            elif isinstance(part, str):
                text_content.append(part)
            else:
                text_content.append(str(part))  # Fallback for other types
        return "".join(text_content)
