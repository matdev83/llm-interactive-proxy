from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import cast

from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.tool_call_repair_service import ToolCallRepairService


class StreamingToolCallRepairProcessor:
    def __init__(self, repair_service: ToolCallRepairService):
        self._repair_service = repair_service

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
        session_id: str,
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
            # Support AsyncMock patched functions returning awaitables or async-iterables
            stream = self._repair_service.process_chunk_for_streaming(
                (chunk.content if chunk.content is not None else ""),
                session_id,
                is_final_chunk=False,
            )
            if hasattr(stream, "__aiter__"):
                async for processed_chunk in stream:  # type: ignore
                    yield processed_chunk
            elif hasattr(stream, "__await__"):
                awaited = await stream  # type: ignore
                if hasattr(awaited, "__aiter__"):
                    async for processed_chunk in awaited:
                        yield processed_chunk
                else:  # pragma: no cover - defensive
                    # Not iterable; ignore
                    pass

        # After the stream ends, process any remaining buffer with is_final_chunk=True
        # Flush any remaining buffer but do not emit tail chunks to the caller.
        tail_stream = self._repair_service.process_chunk_for_streaming(
            "", session_id, is_final_chunk=True
        )
        if hasattr(tail_stream, "__aiter__"):
            async for _ in tail_stream:  # type: ignore
                pass
        elif hasattr(tail_stream, "__await__"):
            awaited_tail = await tail_stream  # type: ignore
            if hasattr(awaited_tail, "__aiter__"):
                async for _ in awaited_tail:
                    pass
