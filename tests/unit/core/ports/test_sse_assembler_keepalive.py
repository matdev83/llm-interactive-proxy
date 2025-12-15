import pytest
from src.core.ports.sse_assembler import SSEAssembler
from src.core.ports.streaming_contracts import StreamingContent


@pytest.mark.asyncio
async def test_sse_assembler_does_not_drop_keepalive_chunks():
    async def stream():
        yield StreamingContent(
            content="",
            metadata={
                "_keepalive": True,
                "id": "chatcmpl-1",
                "model": "m",
                "created": 0,
            },
            is_done=False,
        )

    assembler = SSEAssembler()
    output = []
    async for chunk in assembler.assemble_stream(stream(), format="sse"):
        output.append(chunk)

    assert any(b'"id": "chatcmpl-1"' in chunk for chunk in output)
    assert any(b"data: [DONE]" in chunk for chunk in output)
