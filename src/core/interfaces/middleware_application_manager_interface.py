from abc import ABC, abstractmethod
from typing import Any

from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,  # Corrected import
)


class IMiddlewareApplicationManager(ABC):
    """
    Interface for managing and applying response middleware.
    """

    @abstractmethod
    async def apply_middleware(
        self,
        content: Any,
        middleware_list: list[IResponseMiddleware] | None = None,
        is_streaming: bool = False,
        stop_event: Any | None = None,
        session_id: str = "",
        context: dict[str, Any] | None = None,
    ) -> Any:
        """
        Applies a list of response middleware to the given content.

        Args:
            content: The content to apply middleware to.
            middleware_list: A list of IResponseMiddleware objects to apply.
            is_streaming: A boolean indicating if the middleware is applied during streaming.
            session_id: The associated session identifier.
            context: Additional context for middleware execution.
            stop_event: An optional event to signal early termination during streaming.
            session_id: The session ID for context-aware processing.

        Returns:
            The content after applying all middleware. For streaming, this might be a generator.
        """
