from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

import httpx

from models import ChatCompletionRequest


class Backend(ABC):
    """Abstract base class for LLM backends."""

    prefix: str

    @abstractmethod
    async def chat_completions(
        self, request: ChatCompletionRequest, client: httpx.AsyncClient
    ) -> Any:
        """Handle a chat completion request."""

    @abstractmethod
    async def list_models(self, client: httpx.AsyncClient) -> Dict[str, Any]:
        """Return a dictionary describing available models."""
