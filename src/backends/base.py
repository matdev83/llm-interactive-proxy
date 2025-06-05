from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Optional, Union

from models import ChatCompletionRequest


class LLMBackend(ABC):
    """Abstract interface for LLM backends."""

    @abstractmethod
    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        *,
        extra_headers: Optional[Dict[str, str]] = None,
        stream: bool = False,
    ) -> Union[Dict, AsyncIterator[bytes]]:
        """Send a chat completion request.

        Args:
            request: Chat completion parameters including messages and model.
            extra_headers: Additional HTTP headers to send with the request.
            stream: If True, return an async iterator yielding byte chunks.
        Returns:
            JSON response from backend or async byte iterator when ``stream`` is
            True.
        """

    @abstractmethod
    async def list_models(
        self, *, extra_headers: Optional[Dict[str, str]] = None
    ) -> Dict:
        """Return a JSON description of available models."""

    @abstractmethod
    def get_available_models(self) -> list[str]:
        """Return a list of model IDs that the backend claims to support."""
