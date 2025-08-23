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

logger = logging.getLogger(__name__)


class RequestProcessor(IRequestProcessor):
    """Implementation of the request processor."""

    def __init__(
        self,
        command_processor: ICommandProcessor,
        backend_processor: IBackendProcessor,
        session_service: ISessionService,
        response_processor: IResponseProcessor,
        session_resolver: ISessionResolver | None = None,
    ) -> None:
        """Initialize the request processor."""
        self._command_processor = command_processor
        self._backend_processor = backend_processor
        self._session_service = session_service
        self._response_processor = response_processor

        self._session_resolver = session_resolver or DefaultSessionResolver()

    async def process_request(
        self, context: RequestContext, request_data: Any
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Process an incoming chat completion request."""
        if not isinstance(request_data, ChatRequest):
            raise TypeError("request_data must be of type ChatRequest")

        session_id: str = await self._session_resolver.resolve_session_id(context)

        messages = request_data.messages
        command_result = await self._command_processor.process_messages(
            messages, session_id, context
        )

        if command_result.command_executed and not command_result.modified_messages:
            await self._record_command_in_session(request_data, session_id)
            return await self._process_command_result(command_result)

        backend_request = request_data
        if command_result.modified_messages:
            backend_request = ChatRequest(
                model=request_data.model,
                messages=command_result.modified_messages,
                temperature=request_data.temperature,
                top_p=request_data.top_p,
                max_tokens=request_data.max_tokens,
                stream=request_data.stream,
                extra_body=request_data.extra_body,
            )

        extra_body = (
            backend_request.extra_body.copy() if backend_request.extra_body else {}
        )
        if "session_id" not in extra_body:
            extra_body["session_id"] = session_id

        backend_request = backend_request.model_copy(update={"extra_body": extra_body})

        backend_response = await self._backend_processor.process_backend_request(
            request=backend_request, session_id=session_id, context=context
        )

        session = await self._session_service.get_session(session_id)

        raw_prompt = ""
        if request_data and getattr(request_data, "messages", None):
            for message in reversed(request_data.messages):
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
                    response=(
                        "<streaming>"
                        if backend_request.stream
                        else str(backend_response.content)
                    ),
                )
            )
        await self._session_service.update_session(session)
        logger.info("Session updated in repository")

        return backend_response

    async def _process_command_result(self, command_result: Any) -> ResponseEnvelope:
        """Process a command-only result into a ResponseEnvelope."""
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

            if isinstance(first, ResponseEnvelope):
                return first

            if isinstance(first, dict):
                return ResponseEnvelope(
                    content=first,
                    headers={"content-type": "application/json"},
                    status_code=200,
                )

            if (
                hasattr(first, "name")
                and hasattr(first, "success")
                and hasattr(first, "message")
                and hasattr(first, "data")
            ):
                content = {
                    "id": "proxy_cmd_processed",
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
        self, request_data: ChatRequest, session_id: str
    ) -> None:
        """Record a command-only request in the session history."""
        session = await self._session_service.get_session(session_id)

        raw_prompt = ""
        if request_data and getattr(request_data, "messages", None):
            for message in reversed(request_data.messages):
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
                        handler="proxy",
                        backend=getattr(
                            session.state.backend_config, "backend_type", None
                        ),
                        model=getattr(session.state.backend_config, "model", None),
                        project=getattr(session.state, "project", None),
                        parameters={
                            "temperature": getattr(request_data, "temperature", None),
                            "top_p": getattr(request_data, "top_p", None),
                            "max_tokens": getattr(request_data, "max_tokens", None),
                        },
                    )
                )
                await self._session_service.update_session(session)
