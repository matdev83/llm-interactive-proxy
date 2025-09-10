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
        content: str,
        middleware_list: list[IResponseMiddleware],  # Changed to IResponseMiddleware
        is_streaming: bool = False,
        stop_event: Any = None,
        session_id: str = "",
    ) -> str | Any:
        """
        Applies a list of response middleware to the given content.

        Args:
            content: The content to apply middleware to.
            middleware_list: A list of IResponseMiddleware objects to apply.
            is_streaming: A boolean indicating if the middleware is applied during streaming.
            stop_event: An optional event to signal early termination during streaming.
            session_id: The session ID for context-aware processing.

        Returns:
            The content after applying all middleware. For streaming, this might be a generator.
        """
