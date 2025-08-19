"""
Request processor implementation.

This module provides the implementation of the request processor interface.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.response_processor_interface import IResponseProcessor
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.session_resolver_service import DefaultSessionResolver
from src.core.transport.fastapi.api_adapters import legacy_to_domain_chat_request

logger = logging.getLogger(__name__)


class RequestProcessor(IRequestProcessor):
    """Implementation of the request processor.

    This service orchestrates the request processing flow, including
    command handling, backend calls, and response processing.
    """

    def __init__(
        self,
        command_processor: ICommandProcessor,
        backend_processor: IBackendProcessor,
        session_service: ISessionService,
        response_processor: IResponseProcessor,
        session_resolver: ISessionResolver | None = None,
    ) -> None:
        """Initialize the request processor.

        Args:
            command_processor: Service for processing commands
            backend_processor: Service for processing backend requests
            session_service: Service for managing sessions
            response_processor: Service for processing responses
            session_resolver: Optional service for resolving session IDs
        """
        self._command_processor = command_processor
        self._backend_processor = backend_processor
        self._session_service = session_service
        self._response_processor = response_processor

        # Use provided session resolver or create a default one
        self._session_resolver = session_resolver or DefaultSessionResolver()

    async def process_request(
        self, context: RequestContext, request_data: Any
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Process an incoming chat completion request.

        Args:
            context: Transport-agnostic request context containing headers/cookies/state
            request_data: The parsed request data

        Returns:
            An appropriate response object
        """
        # Convert legacy request to domain model if needed
        domain_request = request_data
        if not isinstance(request_data, ChatRequest):
            domain_request = legacy_to_domain_chat_request(request_data)

        # Resolve session ID using the session resolver
        session_id: str = await self._session_resolver.resolve_session_id(context)

        # Process commands
        messages = domain_request.messages
        command_result = await self._command_processor.process_commands(
            messages, session_id, context
        )

        # If command-only response, handle it
        if command_result.command_executed and not command_result.modified_messages:
            # If messages are empty after command processing, it's a command-only request
            # Record the command in session history
            await self._record_command_in_session(domain_request, session_id)
            return await self._process_command_result(command_result)

        # Process backend request
        backend_request = domain_request
        if command_result.modified_messages:
            # Update request with modified messages
            backend_request = ChatRequest(
                model=domain_request.model,
                messages=command_result.modified_messages,
                temperature=domain_request.temperature,
                top_p=domain_request.top_p,
                max_tokens=domain_request.max_tokens,
                stream=domain_request.stream,
                extra_body=domain_request.extra_body,
            )

        # Call backend processor
        backend_response = await self._backend_processor.process_backend_request(
            request=backend_request, session_id=session_id, context=context
        )

        # Ensure session interaction is recorded. BackendProcessor is expected to
        # handle this, but some test doubles (or older mocks) may not. As a
        # defensive fallback, update the session here if the backend didn't.
        session = await self._session_service.get_session(session_id)

        # Extract raw prompt from original request to preserve user input including commands
        raw_prompt = ""
        if domain_request and getattr(domain_request, "messages", None):
            for message in reversed(domain_request.messages):
                role = (
                    message.get("role")
                    if isinstance(message, dict)
                    else getattr(message, "role", None)
                )
                if role == "user":
                    content = (
                        message.get("content")
                        if isinstance(message, dict)
                        else getattr(message, "content", None)
                    )
                    raw_prompt = content if isinstance(content, str) else str(content)
                    break

        # Only add a new interaction if none exist or last prompt differs
        try:
            last = session.history[-1] if session.history else None
            last_prompt = getattr(last, "prompt", None) if last else None
        except Exception:
            last_prompt = None

        if raw_prompt and last_prompt != raw_prompt:
            from src.core.domain.session import SessionInteraction

            session.add_interaction(
                SessionInteraction(
                    prompt=raw_prompt,
                    handler="backend",
                    backend=(
                        str(getattr(session.state.backend_config, "backend_type", ""))
                        if getattr(session.state.backend_config, "backend_type", None)
                        is not None
                        else None
                    ),
                    model=(
                        str(getattr(session.state.backend_config, "model", ""))
                        if getattr(session.state.backend_config, "model", None)
                        is not None
                        else None
                    ),
                    project=(
                        str(getattr(session.state, "project", ""))
                        if getattr(session.state, "project", None) is not None
                        else None
                    ),
                    parameters={
                        "temperature": getattr(backend_request, "temperature", None),
                        "top_p": getattr(backend_request, "top_p", None),
                        "max_tokens": getattr(backend_request, "max_tokens", None),
                    },
                    response="<streaming>" if backend_request.stream else str(backend_response.content),
                )
            )
        await self._session_service.update_session(session)
        logger.info("Session updated in repository")

        # Return the backend response
        return backend_response

    async def _process_command_result(self, command_result: Any) -> ResponseEnvelope:
        """Process a command-only result into a ResponseEnvelope.

        This method exists to allow tests to patch it when they want to
        inject specific command result payloads. The default implementation
        will take the first item from command_result.command_results and
        wrap it into a ResponseEnvelope if it's a dict or dataclass-like
        structure.
        """
        try:
            first = None
            if getattr(command_result, "command_results", None):
                first = command_result.command_results[0]

            if first is None:
                return ResponseEnvelope(
                    content={},
                    headers={"content-type": "application/json"},
                    status_code=200,
                )

            # If it's already a ResponseEnvelope-like, return as-is
            if isinstance(first, ResponseEnvelope):
                return first

            # If it's a dict, return wrapped
            if isinstance(first, dict):
                return ResponseEnvelope(
                    content=first,
                    headers={"content-type": "application/json"},
                    status_code=200,
                )

            # If it has the expected attributes, extract them
            if (
                hasattr(first, "name")
                and hasattr(first, "success")
                and hasattr(first, "message")
                and hasattr(first, "data")
            ):
                content = {
                    "id": "proxy_cmd_processed",  # Add this line
                    "name": first.name,
                    "success": first.success,
                    "message": first.message,
                    "data": first.data,
                }
                return ResponseEnvelope(
                    content=content,
                    headers={"content-type": "application/json"},
                    status_code=200,
                )
            else:
                # Generic fallback for other objects
                content = {
                    k: getattr(first, k) for k in dir(first) if not k.startswith("_")
                }

            return ResponseEnvelope(
                content=content,
                headers={"content-type": "application/json"},
                status_code=200,
            )
        except Exception:
            return ResponseEnvelope(
                content={},
                headers={"content-type": "application/json"},
                status_code=200,
            )

    async def _record_command_in_session(
        self, domain_request: ChatRequest, session_id: str
    ) -> None:
        """Record a command-only request in the session history."""
        session = await self._session_service.get_session(session_id)

        # Extract raw prompt from original request
        raw_prompt = ""
        if domain_request and getattr(domain_request, "messages", None):
            for message in reversed(domain_request.messages):
                role = (
                    message.get("role")
                    if isinstance(message, dict)
                    else getattr(message, "role", None)
                )
                if role == "user":
                    content = (
                        message.get("content")
                        if isinstance(message, dict)
                        else getattr(message, "content", None)
                    )
                    raw_prompt = content if isinstance(content, str) else str(content)
                    break

        # Only add if prompt exists and differs from last
        if raw_prompt:
            try:
                last = session.history[-1] if session.history else None
                last_prompt = getattr(last, "prompt", None) if last else None
            except Exception:
                last_prompt = None

            if last_prompt != raw_prompt:
                from src.core.domain.session import SessionInteraction

                session.add_interaction(
                    SessionInteraction(
                        prompt=raw_prompt,
                        handler="proxy",  # Command-only requests are handled by proxy
                        backend=getattr(
                            session.state.backend_config, "backend_type", None
                        ),
                        model=getattr(session.state.backend_config, "model", None),
                        project=getattr(session.state, "project", None),
                        parameters={
                            "temperature": getattr(domain_request, "temperature", None),
                            "top_p": getattr(domain_request, "top_p", None),
                            "max_tokens": getattr(domain_request, "max_tokens", None),
                        },
                    )
                )
                await self._session_service.update_session(session)
