from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

import httpx


class IHttpClientManager(Protocol):
    """Interface for managing HTTP client lifecycle during validation."""

    @abstractmethod
    def get_or_create_client(self) -> httpx.AsyncClient:
        """Get or create a managed HTTP client instance.

        Returns:
            An AsyncClient instance that is tracked for cleanup.
        """
        ...

    @abstractmethod
    async def cleanup(self) -> None:
        """Clean up managed HTTP client resources.

        Closes the client if it exists and awaits/cancels any pending cleanup tasks.
        """
        ...
