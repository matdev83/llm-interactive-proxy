"""
Response processing middleware for handling cross-cutting concerns like loop detection and API key redaction.


This module provides a pluggable middleware system that can process responses
from any backend without coupling the loop detection logic to individual connectors.

Note: For request processing (e.g., API key redaction), see request_middleware.py

IMPORTANT: This module maintains backward compatibility while the codebase transitions
to the new SOLID architecture. Some components are re-exported from the new locations.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class RetryAfterMiddleware(BaseHTTPMiddleware):
    """Middleware for handling retry-after headers."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Process the request before and after the call to the next middleware or route handler.

        Args:
            request: The request object
            call_next: The next middleware or route handler

        Returns:
            The response object
        """
        response = await call_next(request)
        return response


# Stub for backward compatibility
def configure_loop_detection_middleware(
    app_or_config: FastAPI | Any | None = None, config: Any | None = None
) -> None:
    """Configure loop detection middleware.

    This configures the global middleware instance for backward compatibility.

    Args:
        app_or_config: Either a FastAPI application or config object
        config: The loop detection configuration (when first arg is FastAPI)
    """
    global _global_middleware

    # Handle both calling styles:
    # configure_loop_detection_middleware(config) - direct config
    # configure_loop_detection_middleware(app, config) - app and config
    actual_config = None
    if config is not None:
        # Called as (app, config)
        actual_config = config
    elif app_or_config is not None and not isinstance(app_or_config, FastAPI):
        # Called as (config) - first arg is actually the config
        actual_config = app_or_config

    if actual_config is None:
        return

    # Remove any existing loop detection processors
    _global_middleware.remove_processor(LoopDetectionProcessor)

    # Add new processor if enabled
    if hasattr(actual_config, "enabled") and actual_config.enabled:
        processor = LoopDetectionProcessor(actual_config)
        _global_middleware.add_processor(processor)

    logger.debug(
        f"Configured loop detection middleware: enabled={getattr(actual_config, 'enabled', False)}, processors={len(_global_middleware.middleware_stack)}"
    )


# Backward compatibility exports
class RequestContext:
    """Backward compatibility stub for RequestContext."""

    def __init__(
        self,
        session_id: str,
        backend_type: str,
        model: str,
        is_streaming: bool,
        **kwargs: Any,
    ) -> None:
        self.session_id = session_id
        self.backend_type = backend_type
        self.model = model
        self.is_streaming = is_streaming
        self.request_data = kwargs.get("request_data")
        self.metadata = kwargs


class ResponseProcessor:
    """Backward compatibility stub for ResponseProcessor."""

    def should_process(self, response: Any, context: Any) -> bool:
        return False

    async def process(self, response: Any, context: Any) -> Any:
        return response


class LoopDetectionProcessor(ResponseProcessor):
    """Backward compatibility stub for LoopDetectionProcessor."""

    def __init__(self, config: Any) -> None:
        self.config = config
        self._detectors: dict[str, Any] = {}

    def should_process(self, response: Any, context: Any) -> bool:
        return self.config.enabled if hasattr(self.config, "enabled") else False

    def _get_or_create_detector(self, session_id: str) -> Any:
        if session_id not in self._detectors:
            from src.loop_detection.detector import LoopDetector

            self._detectors[session_id] = LoopDetector(config=self.config)
        return self._detectors[session_id]

    async def process(self, response: Any, context: Any) -> Any:
        return response

    def cleanup_session(self, session_id: str) -> None:
        if session_id in self._detectors:
            del self._detectors[session_id]


class ResponseMiddleware:
    """Backward compatibility stub for ResponseMiddleware."""

    def __init__(self) -> None:
        self.middleware_stack: list[Any] = []

    def add_processor(self, processor: Any) -> None:
        self.middleware_stack.append(processor)

    def remove_processor(self, processor_type: Any) -> None:
        self.middleware_stack = [
            p for p in self.middleware_stack if not isinstance(p, processor_type)
        ]

    async def process_response(self, response: Any, context: Any) -> Any:
        result = response
        for processor in self.middleware_stack:
            if processor.should_process(result, context):
                result = await processor.process(result, context)
        return result


# Global middleware instance for backward compatibility
_global_middleware: ResponseMiddleware = ResponseMiddleware()


def get_response_middleware() -> ResponseMiddleware:
    """Get the global response middleware instance."""
    return _global_middleware
