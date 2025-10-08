from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    ProcessedResponse,
)
from src.core.services.middleware_application_manager import MiddlewareApplicationManager
from src.core.services.streaming.middleware_application_processor import (
    MiddlewareApplicationProcessor,
)
from src.core.domain.streaming_content import StreamingContent


class _FalsyContentMiddleware(IResponseMiddleware):
    def __init__(self, content: object) -> None:
        super().__init__()
        self._content = content

    async def process(
        self,
        response: ProcessedResponse | object,
        session_id: str,
        context: dict[str, object],
        is_streaming: bool = False,
        stop_event: object | None = None,
    ) -> ProcessedResponse:
        metadata = {}
        usage = None
        if isinstance(response, ProcessedResponse):
            metadata = response.metadata
            usage = response.usage
        return ProcessedResponse(content=self._content, metadata=metadata, usage=usage)


@pytest.mark.asyncio
async def test_non_streaming_preserves_falsy_content() -> None:
    middleware = _FalsyContentMiddleware({})
    manager = MiddlewareApplicationManager([middleware])

    result = await manager.apply_middleware("ignored")

    assert result == {}


@pytest.mark.asyncio
async def test_streaming_preserves_falsy_content() -> None:
    middleware = _FalsyContentMiddleware([])
    manager = MiddlewareApplicationManager([middleware])

    async def _source() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content="initial", metadata={"step": 1})

    stream = await manager.apply_middleware(
        _source(),
        is_streaming=True,
        session_id="session",
    )

    chunks = [chunk async for chunk in stream]
    assert len(chunks) == 1
    assert isinstance(chunks[0], ProcessedResponse)
    assert chunks[0].content == []
    assert chunks[0].metadata == {"step": 1}


@pytest.mark.asyncio
async def test_stream_processor_preserves_falsy_content() -> None:
    middleware = _FalsyContentMiddleware(0)
    processor = MiddlewareApplicationProcessor([middleware])
    chunk = StreamingContent(content="initial", metadata={"session_id": "s"})

    processed = await processor.process(chunk)

    assert processed.content == 0
    assert processed.metadata == {"session_id": "s"}
