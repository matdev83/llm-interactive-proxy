from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import cast

from src.core.domain.streaming_response_processor import StreamingContent
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.streaming.tool_call_repair_processor import (
    ToolCallRepairProcessor,
)


class StreamingToolCallRepairProcessor:
    def __init__(self, tool_call_repair_processor: ToolCallRepairProcessor):
        self._tool_call_repair_processor = tool_call_repair_processor

    async def process_chunks(
        self,
        chunk_source: (
            AsyncIterator[ProcessedResponse]
            | Callable[
                [],
                AsyncIterator[ProcessedResponse]
                | Awaitable[AsyncIterator[ProcessedResponse]],
            ]
            | Awaitable[AsyncIterator[ProcessedResponse]]
        ),
        session_id: str,  # session_id is no longer needed by this processor
    ) -> AsyncIterator[ProcessedResponse]:
        """Processes streaming chunks to repair tool calls.

        Accepts either an async iterator, a callable returning an async iterator,
        or an awaitable that resolves to an async iterator. This makes it robust
        against tests using AsyncMock in different forms.
        """
        iterator: AsyncIterator[ProcessedResponse]

        # Normalize chunk_source to an async iterator
        if callable(chunk_source):
            result = chunk_source()  # type: ignore[misc]
            if hasattr(result, "__await__"):
                iterator = await cast(
                    Awaitable[AsyncIterator[ProcessedResponse]], result
                )
            else:
                iterator = cast(AsyncIterator[ProcessedResponse], result)
        elif hasattr(chunk_source, "__await__"):
            iterator = await cast(
                Awaitable[AsyncIterator[ProcessedResponse]], chunk_source
            )
        else:
            iterator = cast(AsyncIterator[ProcessedResponse], chunk_source)

        async for chunk in iterator:
            streaming_content_chunk = StreamingContent(
                content=chunk.content or "",
                is_done=False,  # Assume not done until the last chunk
                metadata=chunk.metadata,
                usage=chunk.usage,
                # raw_data=chunk.raw_data # ProcessedResponse doesn't have raw_data
            )
            processed_streaming_content = (
                await self._tool_call_repair_processor.process(streaming_content_chunk)
            )
            if processed_streaming_content.content:
                yield ProcessedResponse(
                    content=processed_streaming_content.content,
                    usage=processed_streaming_content.usage,
                    metadata=processed_streaming_content.metadata,
                )

        # Process final chunk to flush any remaining buffer
        final_streaming_content = await self._tool_call_repair_processor.process(
            StreamingContent(content="", is_done=True)
        )
        if final_streaming_content.content:
            yield ProcessedResponse(
                content=final_streaming_content.content,
                usage=final_streaming_content.usage,
                metadata=final_streaming_content.metadata,
            )
