from typing import Any  # Added this import
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.streaming_response_processor import StreamingContent
from src.core.interfaces.response_processor_interface import IResponseMiddleware
from src.core.services.middleware_application_manager import (
    MiddlewareApplicationManager,
)


class MockMiddleware(IResponseMiddleware):
    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        # Simple middleware that appends a string
        if hasattr(response, "content"):
            response.content = (response.content or "") + "_processed"
        return response


class MockStreamingMiddleware(IResponseMiddleware):
    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        # Simple streaming middleware that appends a string
        if isinstance(response, StreamingContent):
            response.content = (response.content or "") + "_streamed"
        return response


@pytest.fixture
def manager():
    return MiddlewareApplicationManager([MockMiddleware(), MockStreamingMiddleware()])


@pytest.mark.asyncio
async def test_apply_middleware_non_streaming(manager):
    middleware_list = [MockMiddleware()]
    content = "initial_content"
    processed_content = await manager.apply_middleware(
        content, middleware_list, is_streaming=False
    )
    assert processed_content == "initial_content_processed"


@pytest.mark.asyncio
async def test_apply_middleware_multiple_non_streaming(manager):
    middleware_list = [MockMiddleware(), MockMiddleware()]
    content = "initial_content"
    processed_content = await manager.apply_middleware(
        content, middleware_list, is_streaming=False
    )
    assert processed_content == "initial_content_processed_processed"


@pytest.mark.asyncio
async def test_apply_middleware_streaming(manager):
    middleware_list = [MockStreamingMiddleware()]

    async def generate_chunks():
        yield StreamingContent(content="chunk1", is_done=False)
        yield StreamingContent(content="chunk2", is_done=True)

    content_iterator = generate_chunks()
    processed_iterator = await manager.apply_middleware(
        content_iterator, middleware_list, is_streaming=True
    )

    chunks = []
    async for chunk in processed_iterator:
        chunks.append(chunk)

    assert len(chunks) == 2
    assert chunks[0].content == "chunk1_streamed"
    assert not chunks[0].is_done
    assert chunks[1].content == "chunk2_streamed"
    assert chunks[1].is_done


@pytest.mark.asyncio
async def test_apply_middleware_multiple_streaming(manager):
    middleware_list = [MockStreamingMiddleware(), MockStreamingMiddleware()]

    async def generate_chunks():
        yield StreamingContent(content="chunk1", is_done=False)
        yield StreamingContent(content="chunk2", is_done=True)

    content_iterator = generate_chunks()
    processed_iterator = await manager.apply_middleware(
        content_iterator, middleware_list, is_streaming=True
    )

    chunks = []
    async for chunk in processed_iterator:
        chunks.append(chunk)

    assert len(chunks) == 2
    assert chunks[0].content == "chunk1_streamed_streamed"
    assert not chunks[0].is_done
    assert chunks[1].content == "chunk2_streamed_streamed"
    assert chunks[1].is_done


@pytest.mark.asyncio
async def test_apply_middleware_empty_list(manager):
    middleware_list = []
    content = "initial_content"
    processed_content = await manager.apply_middleware(
        content, middleware_list, is_streaming=False
    )
    assert processed_content == "initial_content"

    async def generate_chunks():
        yield StreamingContent(content="chunk1", is_done=True)

    content_iterator = generate_chunks()
    processed_iterator = await manager.apply_middleware(
        content_iterator, middleware_list, is_streaming=True
    )
    chunks = []
    async for chunk in processed_iterator:
        chunks.append(chunk)
    assert len(chunks) == 1
    assert chunks[0].content == "chunk1"


@pytest.mark.asyncio
async def test_apply_middleware_with_stop_event_non_streaming(manager):
    stop_event = MagicMock()
    middleware_list = [MockMiddleware()]
    content = "initial_content"
    processed_content = await manager.apply_middleware(
        content, middleware_list, is_streaming=False, stop_event=stop_event
    )
    assert processed_content == "initial_content_processed"
    # Verify stop_event was passed to middleware (mocking process method to check context)
    mock_middleware_instance = middleware_list[0]
    mock_middleware_instance.process = AsyncMock(
        side_effect=mock_middleware_instance.process
    )
    await manager.apply_middleware(
        content, middleware_list, is_streaming=False, stop_event=stop_event
    )
    mock_middleware_instance.process.assert_called_once()
    assert mock_middleware_instance.process.call_args[0][2]["stop_event"] == stop_event


@pytest.mark.asyncio
async def test_apply_middleware_with_stop_event_streaming(manager):
    stop_event = MagicMock()
    stop_event.is_set.return_value = True
    middleware_list = [MockStreamingMiddleware()]

    async def generate_chunks():
        yield StreamingContent(content="chunk1", is_done=False)

    content_iterator = generate_chunks()
    processed_iterator = await manager.apply_middleware(
        content_iterator, middleware_list, is_streaming=True, stop_event=stop_event
    )

    chunks = []
    async for chunk in processed_iterator:
        chunks.append(chunk)

    assert len(chunks) == 0
    # Verification of stop_event in streaming middleware would require more intricate mocking of the async generator.
    # For now, relying on the non-streaming test for stop_event passing.
