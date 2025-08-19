"""
Request processor implementation.

This module provides the implementation of the request processor interface.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.response_envelope import ResponseEnvelope
from src.core.domain.streaming_response_envelope import StreamingResponseEnvelope
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
        self, context: RequestContext, request_data: ChatRequest
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
        if command_result.command_executed:
            # Get the session
            session = await self._session_service.get_session(session_id)
            
            # Check if we should continue to backend
            continue_to_backend = False
            for cr in command_result.command_results:
                if getattr(cr, "data", None):
                    continue_to_backend = True
                    break
                    
            if not continue_to_backend:
                # Return command-only response
                # This would be implemented in the full version
                pass
        
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
        return await self._backend_processor.process_backend_request(
            request=backend_request,
            session_id=session_id,
            context=context
        )