"""
Request processor implementation.

This module provides the implementation of the request processor interface.
Refactored to use decomposed services following SOLID principles.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from src.core.domain.chat import ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_request_manager_interface import IBackendRequestManager
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.response_manager_interface import IResponseManager
from src.core.interfaces.session_manager_interface import ISessionManager
from src.core.services.application_state_service import (
    get_default_application_state,
)

logger = logging.getLogger(__name__)


class RequestProcessor(IRequestProcessor):
    """Implementation of the request processor using decomposed services."""

    def __init__(
        self,
        command_processor: ICommandProcessor,
        session_manager: ISessionManager,
        backend_request_manager: IBackendRequestManager,
        response_manager: IResponseManager,
    ) -> None:
        """Initialize the request processor with decomposed services."""
        self._command_processor = command_processor
        self._session_manager = session_manager
        self._backend_request_manager = backend_request_manager
        self._response_manager = response_manager

    async def process_request(
        self, context: RequestContext, request_data: Any
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Process an incoming chat completion request using decomposed services."""
        logger.debug(
            f"RequestProcessor.process_request called with session_id: {getattr(context, 'session_id', 'unknown')}"
        )
        if not isinstance(request_data, ChatRequest):
            raise TypeError("request_data must be of type ChatRequest")

        # Resolve session and update agent if needed
        session_id = await self._session_manager.resolve_session_id(context)
        session = await self._session_manager.get_session(session_id)
        session = await self._session_manager.update_session_agent(
            session, request_data.agent
        )

        logger.debug(f"Resolved session_id: {session_id}")
        logger.debug(
            f"Request data type: {type(request_data)}, model: {getattr(request_data, 'model', 'unknown')}"
        )

        # Process commands in the request
        command_result = await self._handle_command_processing(
            request_data, session_id, context
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

        # Check if we should take the command-only path
        if self._should_process_command_only(command_result):
            logger.debug(f"Taking command result path for session {session_id}")
            logger.info(
                "Command executed with no modified messages - returning command result without backend call"
            )
            await self._session_manager.record_command_in_session(
                request_data, session_id
            )
            return await self._response_manager.process_command_result(
                command_result, session
            )

        # Prepare backend request
        backend_request = await self._backend_request_manager.prepare_backend_request(
            request_data, command_result
        )

        if backend_request is None:
            # Skip backend call and return command result directly
            logger.debug(
                f"Command executed without backend call, processing command result for session {session_id}"
            )
            logger.info(
                f"Command executed without backend call, processing command result for session {session_id}"
            )
            await self._session_manager.record_command_in_session(
                request_data, session_id
            )
            return await self._response_manager.process_command_result(
                command_result, session
            )

        # Add session_id to extra_body if not present
        async def _resolve_extra_body(value: Any) -> dict[str, Any] | None:
            v = value
            try:
                # If attribute is a function/mocked callable, call it
                if callable(v):
                    v = v()
                # If result is awaitable/coroutine, await it
                if hasattr(v, "__await__"):
                    v = await v  # type: ignore[func-returns-value]
                # Expect dict-like or None
                if v is None:
                    return None
                if isinstance(v, dict):
                    return v
                # Some domain objects may have model_dump method
                if hasattr(v, "model_dump"):
                    dumped = v.model_dump()
                    return dumped if isinstance(dumped, dict) else None
            except Exception:
                return None
            return None

        resolved_extra = await _resolve_extra_body(
            getattr(backend_request, "extra_body", None)
        )
        extra_body: dict[str, Any] = resolved_extra.copy() if resolved_extra else {}
        if "session_id" not in extra_body:
            extra_body["session_id"] = session_id
        backend_request = backend_request.model_copy(update={"extra_body": extra_body})

        # Process backend request with retry handling
        logger.info(
            f"Calling backend for session {session_id} with request: {backend_request}"
        )
        backend_response = await self._backend_request_manager.process_backend_request(
            backend_request, session_id, context
        )
        logger.info(f"Backend response for session {session_id}: {backend_response}")

        # Update session history with the backend interaction
        await self._session_manager.update_session_history(
            request_data, backend_request, backend_response, session_id
        )

        return backend_response

    async def _process_command_result(
        self, command_result: ProcessedResult, session: Any
    ) -> ResponseEnvelope:
        """Compatibility wrapper used by legacy tests to process command-only results.

        Delegates to the injected response manager.
        """
        return await self._response_manager.process_command_result(
            command_result, session
        )

    def _should_process_command_only(self, command_result: ProcessedResult) -> bool:
        """Determine if we should process command result without backend call."""
        return command_result.command_executed and not command_result.modified_messages

    async def _handle_command_processing(
        self, request_data: ChatRequest, session_id: str, context: RequestContext
    ) -> ProcessedResult:
        """Handle command processing with global disable check and fallback."""
        # If commands are globally disabled, skip command processing
        try:
            if get_default_application_state().get_disable_commands():
                return ProcessedResult(
                    command_executed=False,
                    modified_messages=[],
                    command_results=[],
                )
            else:
                # Work on a deep copy to avoid mutating the original request messages
                messages_copy = copy.deepcopy(request_data.messages)
                return await self._command_processor.process_messages(
                    messages_copy, session_id, context
                )
        except Exception:
            # Fallback to normal processing if state service is unavailable
            messages_copy = copy.deepcopy(request_data.messages)
            return await self._command_processor.process_messages(
                messages_copy, session_id, context
            )
