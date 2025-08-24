"""
Request processor implementation.

This module provides the implementation of the request processor interface.
"""

from __future__ import annotations

import copy
import logging
import time
from typing import Any

from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.response_processor_interface import IResponseProcessor
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.command_service import CommandResultWrapper
from src.core.services.empty_response_middleware import EmptyResponseRetryError
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
        logger.debug(
            f"RequestProcessor.process_request called with session_id: {getattr(context, 'session_id', 'unknown')}"
        )
        if not isinstance(request_data, ChatRequest):
            raise TypeError("request_data must be of type ChatRequest")

        session_id: str = await self._session_resolver.resolve_session_id(context)
        logger.debug(f"Resolved session_id: {session_id}")
        logger.debug(
            f"Request data type: {type(request_data)}, model: {getattr(request_data, 'model', 'unknown')}"
        )

        session = await self._session_service.get_session(session_id)

        # Set session agent from request_data if present
        if request_data.agent is not None and request_data.agent != session.agent:
            logger.debug(
                f"Setting session agent from request_data: {request_data.agent}"
            )
            session.agent = request_data.agent
            await self._session_service.update_session(session)

        logger.debug(f"Is Cline agent: {session.is_cline_agent}")

        # If commands are globally disabled, skip command processing
        try:
            from src.core.services.application_state_service import (
                get_default_application_state,
            )

            if get_default_application_state().get_disable_commands():
                command_result: ProcessedResult = ProcessedResult(
                    command_executed=False,
                    modified_messages=[],
                    command_results=[],
                )
            else:
                # Work on a deep copy to avoid mutating the original request messages
                messages_copy = copy.deepcopy(request_data.messages)
                command_result = await self._command_processor.process_messages(
                    messages_copy, session_id, context
                )
        except Exception:
            # Fallback to normal processing if state service is unavailable
            messages_copy = copy.deepcopy(request_data.messages)
            command_result = await self._command_processor.process_messages(
                messages_copy, session_id, context
            )

        # Debug logging to understand command processing behavior
        logger.debug(
            f"Command processing result: command_executed={command_result.command_executed}, modified_messages={len(command_result.modified_messages) if hasattr(command_result.modified_messages, '__len__') else 0}, command_results={len(command_result.command_results) if hasattr(command_result.command_results, '__len__') else 0}"
        )
        logger.info(
            f"Command processing result: command_executed={command_result.command_executed}, "
            f"modified_messages={len(command_result.modified_messages) if hasattr(command_result.modified_messages, '__len__') else 0}, "
            f"command_results={len(command_result.command_results) if hasattr(command_result.command_results, '__len__') else 0}"
        )

        # For Cline non-command messages, we need to ensure we call the backend
        # even when command processing was attempted but no command was found
        logger.debug(
            f"Checking command result path: command_executed={command_result.command_executed}, modified_messages={len(command_result.modified_messages) if hasattr(command_result.modified_messages, '__len__') else 0}"
        )
        logger.debug(f"Session ID: {session_id}")
        session = await self._session_service.get_session(session_id)
        logger.debug(f"Is Cline agent: {session.is_cline_agent}")

        if command_result.command_executed and not command_result.modified_messages:
            logger.debug(f"Taking command result path for session {session_id}")
            logger.info(
                "Command executed with no modified messages - returning command result without backend call"
            )
            await self._record_command_in_session(request_data, session_id)
            return await self._process_command_result(command_result, session_id)

        logger.debug(f"Command result messages: {command_result.modified_messages}")

        backend_request: ChatRequest | None = request_data
        if command_result.command_executed and command_result.modified_messages:
            # Check if all modified messages are essentially empty (just whitespace)
            def _message_has_content(message: Any) -> bool:
                role = (
                    message.get("role")
                    if isinstance(message, dict)
                    else getattr(message, "role", None)
                )
                if role != "user":
                    return False
                content = (
                    message.get("content")
                    if isinstance(message, dict)
                    else getattr(message, "content", None)
                )
                if content is None:
                    return False
                # If content is a string, check non-empty after strip
                if isinstance(content, str):
                    return bool(content.strip())
                # If content is a list (multimodal parts), treat non-empty as content
                if isinstance(content, list):
                    return len(content) > 0
                # Fallback for other types: truthiness
                return bool(content)

            has_content = any(
                _message_has_content(m) for m in command_result.modified_messages
            )

            if has_content:
                # Normalize messages to domain ChatMessage instances
                normalized_messages: list[ChatMessage] = []
                for m in command_result.modified_messages:
                    if isinstance(m, ChatMessage):
                        normalized_messages.append(m)
                    elif isinstance(m, dict):
                        normalized_messages.append(ChatMessage(**m))
                    else:
                        # Best-effort conversion
                        normalized_messages.append(
                            ChatMessage(
                                role=getattr(m, "role", "user"),
                                content=getattr(m, "content", ""),
                            )
                        )

                backend_request = ChatRequest(
                    model=request_data.model,
                    messages=normalized_messages,
                    temperature=request_data.temperature,
                    top_p=request_data.top_p,
                    max_tokens=request_data.max_tokens,
                    stream=request_data.stream,
                    extra_body=request_data.extra_body,
                )
            else:
                # All modified messages are empty, skip backend call
                backend_request = None  # type: ignore[assignment]

        if backend_request is None:
            # Skip backend call and return command result directly
            logger.debug(
                f"Command executed without backend call, processing command result for session {session_id}"
            )
            logger.info(
                f"Command executed without backend call, processing command result for session {session_id}"
            )
            await self._record_command_in_session(request_data, session_id)
            return await self._process_command_result(command_result, session_id)

        extra_body = (
            backend_request.extra_body.copy() if backend_request.extra_body else {}
        )
        if "session_id" not in extra_body:
            extra_body["session_id"] = session_id

        backend_request = backend_request.model_copy(update={"extra_body": extra_body})

        # Process backend request with empty response retry handling
        logger.info(
            f"Calling backend for session {session_id} with request: {backend_request}"
        )
        backend_response = await self._process_backend_request_with_retry(
            backend_request, session_id, context
        )
        logger.info(f"Backend response for session {session_id}: {backend_response}")

        # Empty response handling is already done in _process_backend_request_with_retry above

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
                    if isinstance(content, str):
                        raw_prompt = content
                    elif isinstance(content, list):
                        # Multimodal: concatenate any text parts; otherwise stringify
                        try:
                            text_parts = []
                            for part in content:
                                if isinstance(part, dict):
                                    if part.get("type") == "text" and "text" in part:
                                        text_parts.append(str(part["text"]))
                                elif isinstance(part, str):
                                    text_parts.append(part)
                            raw_prompt = " ".join(t for t in text_parts if t).strip()
                            if not raw_prompt:
                                raw_prompt = str(content)
                        except Exception:
                            raw_prompt = str(content)
                    else:
                        raw_prompt = str(content)
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

    def _create_tool_calls_response(self, command_name: str, arguments: str) -> dict:
        """Create a tool_calls response for Cline agents."""
        logger.debug(
            f"Creating tool calls response for command: {command_name}, arguments: {arguments}"
        )
        import time
        import uuid

        return {
            "id": "proxy_cmd_processed",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "gpt-4",  # Mock model
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": f"call_{uuid.uuid4().hex[:16]}",
                                "type": "function",
                                "function": {
                                    "name": command_name,
                                    "arguments": arguments,
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

    async def _process_command_result(
        self, command_result: ProcessedResult, session_id: str
    ) -> ResponseEnvelope:
        """Process a command-only result into a ResponseEnvelope."""
        if not command_result.command_results:
            return ResponseEnvelope(
                content={},
                headers={"content-type": "application/json"},
                status_code=200,
            )

        first_result = command_result.command_results[0]
        logger.debug(
            f"First command result: {first_result}, type: {type(first_result)}"
        )
        if isinstance(first_result, ResponseEnvelope):
            return first_result

        session = await self._session_service.get_session(session_id)
        is_cline_agent = session.is_cline_agent

        content: dict[str, Any]
        if is_cline_agent:
            # For Cline, we expect a CommandResultWrapper
            if isinstance(first_result, CommandResultWrapper):
                actual_result = first_result.result
                command_name = getattr(actual_result, "name", "unknown_command")
                import json

                # For Cline, all command results are wrapped in an "attempt_completion" tool call
                # The actual command name and its result are passed as arguments
                arguments = json.dumps(
                    {
                        "command_name": command_name,
                        "result": str(actual_result.message or ""),
                    }
                )
                logger.debug(
                    f"Cline agent - creating 'attempt_completion' tool call for command: {command_name}, message: {actual_result.message}"
                )
                content = self._create_tool_calls_response(
                    "attempt_completion", arguments
                )
            else:
                # Fallback for unexpected types
                logger.warning(
                    f"Unexpected result type for Cline agent: {type(first_result)}. Returning unknown_command tool call."
                )
                content = self._create_tool_calls_response(
                    "unknown_command",
                    '{"result": "Unexpected result type for Cline agent"}',
                )
        else:
            # For non-Cline agents, return the message content
            logger.debug(
                f"Non-Cline agent - processing command result as message content: {first_result}"
            )
            message = ""
            if hasattr(first_result, "result") and hasattr(
                first_result.result, "message"
            ):
                message = first_result.result.message
            elif hasattr(first_result, "message"):
                message = first_result.message
            else:
                message = str(first_result)

            logger.debug(f"Non-Cline agent - final message content: {message}")
            content = {
                "id": "proxy_cmd_processed",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "gpt-4",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": message},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }

        return ResponseEnvelope(
            content=content,
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

    async def _process_backend_request_with_retry(
        self, backend_request: ChatRequest, session_id: str, context: RequestContext
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Process backend request with empty response retry handling."""
        try:
            # First attempt
            backend_response = await self._backend_processor.process_backend_request(
                request=backend_request, session_id=session_id, context=context
            )

            # Process the response through middleware (including empty response detection)
            # Only process non-streaming responses that have content
            if (
                hasattr(backend_response, "content")
                and not backend_request.stream
                and backend_response.content is not None
            ):
                # For non-streaming responses, process through response processor
                try:
                    # Process through response processor for empty response detection
                    # This works for both real implementations and mocks in tests
                    await self._response_processor.process_response(
                        backend_response.content, session_id
                    )
                    # If we get here without exception, response was not empty
                    # Return original response (don't replace with processed content)
                    return backend_response
                except EmptyResponseRetryError as e:
                    logger.info(
                        f"Empty response detected, retrying with recovery prompt: {e.recovery_prompt[:100]}..."
                    )
                    # Create retry request with recovery prompt
                    retry_request = await self._create_retry_request(
                        backend_request, e.recovery_prompt
                    )
                    # Retry the request
                    return await self._backend_processor.process_backend_request(
                        request=retry_request, session_id=session_id, context=context
                    )
            else:
                # For streaming responses or responses without content, return as-is
                # TODO: Implement streaming empty response detection if needed
                return backend_response

        except EmptyResponseRetryError as e:
            # This shouldn't happen here since we catch it above, but just in case
            logger.info(
                f"Empty response detected, retrying with recovery prompt: {e.recovery_prompt[:100]}..."
            )
            retry_request = await self._create_retry_request(
                backend_request, e.recovery_prompt
            )
            return await self._backend_processor.process_backend_request(
                request=retry_request, session_id=session_id, context=context
            )

    async def _create_retry_request(
        self, original_request: ChatRequest, recovery_prompt: str
    ) -> ChatRequest:
        """Create a retry request with the recovery prompt appended."""
        # Copy the original messages
        retry_messages = list(original_request.messages)

        # Add the recovery prompt as a user message
        recovery_message = ChatMessage(role="user", content=recovery_prompt)
        retry_messages.append(recovery_message)

        # Create new request with the recovery prompt
        retry_request = ChatRequest(
            model=original_request.model,
            messages=retry_messages,
            temperature=original_request.temperature,
            top_p=original_request.top_p,
            max_tokens=original_request.max_tokens,
            stream=original_request.stream,
            extra_body=original_request.extra_body,
        )

        return retry_request
