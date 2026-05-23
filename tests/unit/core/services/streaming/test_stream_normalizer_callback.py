from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from src.core.ports.streaming_contracts import IStreamProcessor, StreamingContent
from src.core.services.streaming.stream_normalizer import StreamNormalizer


class _CallbackRecorder(IStreamProcessor):
    def __init__(self) -> None:
        self.cancel_callback: Callable[[], Awaitable[None]] | None = None

    async def process(self, content: StreamingContent) -> StreamingContent:
        return content

    def reset(self) -> None:
        return


@pytest.mark.asyncio
async def test_stream_normalizer_sets_cancel_callback_on_processors() -> None:
    recorder = _CallbackRecorder()
    normalizer = StreamNormalizer(processors=[recorder])

    async def dummy_stream() -> AsyncIterator[StreamingContent]:
        yield StreamingContent(content="hi")

    flag = {"called": False}

    async def cancel_cb() -> None:
        flag["called"] = True

    async for _ in normalizer.process_stream(
        dummy_stream(), output_format="objects", cancel_callback=cancel_cb
    ):
        pass

    assert recorder.cancel_callback is cancel_cb  # type: ignore[attr-defined]
    # Ensure callback remains callable
    await recorder.cancel_callback()  # type: ignore[func-returns-value]
    assert flag["called"] is True
