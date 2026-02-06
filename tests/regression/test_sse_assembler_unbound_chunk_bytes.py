from collections.abc import AsyncIterator

import pytest
from src.core.ports.sse_assembler import SSEAssembler
from src.core.ports.streaming_contracts import StreamingContent


async def _async_iter(items: list[StreamingContent]) -> AsyncIterator[StreamingContent]:
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_error_terminal_chunk_does_not_raise_unbound_bytes() -> None:
    assembler = SSEAssembler()
    chunks = [
        StreamingContent(
            content="",
            metadata={
                "provider": "openai",
                "finish_reason": "error",
                "error": {"message": "boom"},
            },
            is_done=True,
        )
    ]

    output = b"".join(
        [chunk async for chunk in assembler.assemble_stream(_async_iter(chunks))]
    )

    assert b"boom" in output
    assert output.endswith(b"data: [DONE]\n\n")
