from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class ProcessedResponse:
    def __init__(
        self,
        content: str = "",
        usage: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.content = content
        self.usage = usage
        self.metadata = metadata or {}


class IResponseProcessor(ABC):
    @abstractmethod
    async def process_response(
        self, response: Any, session_id: str
    ) -> ProcessedResponse:
        pass

    @abstractmethod
    def process_streaming_response(
        self, response_iterator: AsyncIterator[Any], session_id: str
    ) -> AsyncIterator[ProcessedResponse]:
        pass

    @abstractmethod
    async def register_middleware(
        self, middleware: IResponseMiddleware, priority: int = 0
    ) -> None:
        pass


class IResponseMiddleware(ABC):
    @abstractmethod
    async def process(
        self, response: Any, session_id: str, context: dict[str, Any]
    ) -> Any:
        pass
