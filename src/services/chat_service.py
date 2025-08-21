"""
Chat service implementation.

This module provides the chat service implementation for the new architecture.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import FastAPI, Request

from src.core.di.services import get_service_provider
from src.core.interfaces.model_bases import DomainModel, InternalDTO

logger = logging.getLogger(__name__)


class ChatService:
    """Service layer for handling chat completion requests."""

    def __init__(self, app: FastAPI | None = None):
        """
        Initialize the chat service.

        Args:
            app: The FastAPI application
        """
        self.app = app

    async def process_chat_request(
        self,
        http_request: Request,
        request_data: DomainModel | InternalDTO | dict[str, Any],
    ) -> Any:
        """
        Process a chat completion request.

        Args:
            http_request: The HTTP request
            request_data: The request data

        Returns:
            The response
        """
        # Get service provider
        provider: Any = get_service_provider()
        if not provider:
            raise ValueError("Service provider not available")

        # Get services
        from src.core.services.backend_service import BackendService
        from src.core.services.command_service import CommandService
        from src.core.services.session_service_impl import SessionService

        session_service: SessionService = provider.get_service(SessionService)
        command_service: CommandService = provider.get_service(CommandService)
        backend_service: BackendService = provider.get_service(BackendService)

        if not session_service:
            raise ValueError("Session service not available")
        if not command_service:
            raise ValueError("Command service not available")
        if not backend_service:
            raise ValueError("Backend service not available")

        # Type assertions to help mypy understand these are concrete classes
        assert isinstance(session_service, SessionService)
        assert isinstance(command_service, CommandService)
        assert isinstance(backend_service, BackendService)

        # Get session ID
        session_id: str = http_request.headers.get("x-session-id", "default")

        # Convert incoming request to domain ChatRequest (handles dicts/legacy models)
        from src.core.domain.chat import ChatRequest
        from src.core.domain.processed_result import ProcessedResult
        from src.core.transport.fastapi.api_adapters import (
            legacy_to_domain_chat_request,
        )

        domain_request: ChatRequest = legacy_to_domain_chat_request(request_data)

        # Get session (needed for command processing)
        await session_service.get_session(session_id)

        # Process commands
        processed_result: ProcessedResult = await command_service.process_commands(
            domain_request.messages, session_id
        )

        # If a command was executed, return the command result
        if processed_result.command_executed:
            # Return a domain ChatResponse-like dict for command-only results
            return {
                "id": f"cmd-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": domain_request.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "\n".join(
                                result.message
                                for result in processed_result.command_results
                                if result.message
                            ),
                        },
                        "finish_reason": "stop",
                    }
                ],
            }

        # Call the backend service
        from src.core.domain.chat import ChatMessage

        # Convert to domain request
        chat_messages: list[ChatMessage] = [
            ChatMessage(
                role=msg.role,
                content=msg.content,
                name=getattr(msg, "name", None),
                tool_calls=getattr(msg, "tool_calls", None),
                tool_call_id=getattr(msg, "tool_call_id", None),
            )
            for msg in processed_result.modified_messages
        ]

        chat_request: ChatRequest = ChatRequest(
            messages=chat_messages,
            model=domain_request.model,
            stream=domain_request.stream,
            temperature=domain_request.temperature,
            max_tokens=domain_request.max_tokens,
            tools=domain_request.tools,
            tool_choice=domain_request.tool_choice,
            user=domain_request.user,
            session_id=session_id,
        )

        # Call backend service
        return await backend_service.call_completion(
            chat_request, stream=getattr(request_data, "stream", False)
        )
