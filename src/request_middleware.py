"""
Request processing middleware for handling cross-cutting concerns like API key redaction and command filtering.

This module provides a pluggable middleware system that can process requests
before they are sent to any backend without coupling the redaction logic to individual connectors.
"""

from __future__ import annotations

import logging
from typing import Any

from src.security import APIKeyRedactor, ProxyCommandFilter

logger = logging.getLogger(__name__)


class RequestMiddleware:
    """
    Middleware for processing requests before they are sent to backends.

    This provides a pluggable architecture where different middleware components
    can be added without modifying individual backend connectors.
    """

    def __init__(self) -> None:
        self.middleware_stack: list[RequestProcessor] = []

    def add_processor(self, processor: RequestProcessor) -> None:
        """Add a request processor to the middleware stack."""
        self.middleware_stack.append(processor)

    def remove_processor(self, processor_type: type) -> None:
        """Remove all processors of a specific type."""
        self.middleware_stack = [
            p for p in self.middleware_stack if not isinstance(p, processor_type)
        ]

    async def process_request(
        self, messages: list[dict[str, Any]], request_context: RequestContext
    ) -> list[dict[str, Any]]:
        """
        Process messages through all middleware processors.

        Args:
            messages: The messages from the request
            request_context: Context information about the request

        Returns:
            Processed messages
        """
        processed_messages = messages

        for processor in self.middleware_stack:
            if processor.should_process(processed_messages, request_context):
                processed_messages = await processor.process(
                    processed_messages, request_context
                )

        return processed_messages


class RequestProcessor:
    """Base class for request processors."""

    def should_process(
        self, messages: list[dict[str, Any]], context: RequestContext
    ) -> bool:
        """Determine if this processor should handle the messages."""
        return True

    async def process(
        self, messages: list[dict[str, Any]], context: RequestContext
    ) -> list[dict[str, Any]]:
        """Process the messages."""
        return messages


class RequestContext:
    """Context information for request processing."""

    def __init__(
        self,
        session_id: str,
        backend_type: str,
        model: str,
        redaction_enabled: bool = True,
        api_key_redactor: APIKeyRedactor | None = None,
        command_filter: ProxyCommandFilter | None = None,
        **kwargs: Any,
    ) -> None:
        self.session_id = session_id
        self.backend_type = backend_type
        self.model = model
        self.redaction_enabled = redaction_enabled
        self.api_key_redactor = api_key_redactor
        self.command_filter = command_filter
        self.metadata = kwargs


class RedactionProcessor(RequestProcessor):
    """Request processor that handles API key redaction and command filtering for any backend."""

    def should_process(
        self, messages: list[dict[str, Any]], context: RequestContext
    ) -> bool:
        """Only process if redaction is enabled and we have a redactor."""
        return context.redaction_enabled and (
            context.api_key_redactor is not None or context.command_filter is not None
        )

    async def process(
        self, messages: list[dict[str, Any]], context: RequestContext
    ) -> list[dict[str, Any]]:
        """Process messages for API key redaction and command filtering."""
        if not context.redaction_enabled:
            return messages

        processed_messages = []
        for message in messages:
            processed_message = message.copy()
            if "content" in processed_message:
                content = processed_message["content"]
                if content is not None:
                    # Apply API key redaction first
                    if context.api_key_redactor is not None:
                        content = self._redact_message_content(
                            content, context.api_key_redactor
                        )

                    # Apply command filtering second
                    if context.command_filter is not None:
                        content = self._filter_message_content(
                            content, context.command_filter
                        )

                    processed_message["content"] = content
            processed_messages.append(processed_message)

        return processed_messages

    def _redact_message_content(
        self, content: Any, prompt_redactor: APIKeyRedactor
    ) -> Any:
        """Redacts text content within a message string or list of parts."""
        if isinstance(content, str):
            return prompt_redactor.redact(content)
        elif isinstance(content, list):
            # Process parts. Assuming parts are dictionaries as they come from model_dump().
            for part_dict in content:
                if (
                    isinstance(part_dict, dict)
                    and part_dict.get("type") == "text"
                    and "text" in part_dict
                ):
                    part_dict["text"] = prompt_redactor.redact(part_dict["text"])
            return content  # Return the modified list of dicts
        return content  # No change for other types, or if content is None

    def _filter_message_content(
        self, content: Any, command_filter: ProxyCommandFilter
    ) -> Any:
        """Emergency filter to remove proxy commands from message content."""
        if isinstance(content, str):
            return command_filter.filter_commands(content)
        elif isinstance(content, list):
            # Process parts. Assuming parts are dictionaries as they come from model_dump().
            for part_dict in content:
                if (
                    isinstance(part_dict, dict)
                    and part_dict.get("type") == "text"
                    and "text" in part_dict
                ):
                    part_dict["text"] = command_filter.filter_commands(
                        part_dict["text"]
                    )
            return content  # Return the modified list of dicts
        return content  # No change for other types, or if content is None


# Global middleware instance
request_middleware = RequestMiddleware()


def configure_redaction_middleware() -> None:
    """Configure the global redaction middleware."""
    # Remove any existing redaction processors
    request_middleware.remove_processor(RedactionProcessor)

    # Add new redaction processor
    processor = RedactionProcessor()
    request_middleware.add_processor(processor)


def get_request_middleware() -> RequestMiddleware:
    """Get the global request middleware instance."""
    return request_middleware


# FastAPI Middleware Classes
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class CustomHeaderMiddleware(BaseHTTPMiddleware):
    """Middleware to add custom headers to responses."""
    
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        
        # Add custom headers
        response.headers["X-Powered-By"] = "LLM Interactive Proxy"
        response.headers["X-API-Version"] = "1.0"
        
        return response
